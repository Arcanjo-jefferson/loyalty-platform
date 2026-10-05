import asyncio
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import boto3
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError
from botocore.stub import Stubber
from app.dynamodb_repository import DynamoDBCustomerRepository
from app.models import CustomerInput
from app.repository import ConcurrentModification, DuplicatePhone, StorageUnavailable
from app.service import CustomerNotFound, CustomerService
from fake_dynamodb import FakeDynamoDB


TABLE = 'test-customers'


def aws_error(code, reasons=None):
    response = {'Error': {'Code': code, 'Message': 'raw AWS details must not reach clients'}}
    if reasons is not None:
        response['CancellationReasons'] = [{'Code': reason} for reason in reasons]
    return ClientError(response, 'TransactWriteItems')


class DynamoDBRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeDynamoDB()
        self.repo = DynamoDBCustomerRepository(self.client, TABLE)
        self.service = CustomerService(self.repo)

    def data(self, **changes):
        return CustomerInput(**{'first_name': 'Fictional', 'last_name': 'Customer', 'phone': '0871234567', 'date_of_birth': '1990-01-01', **changes})

    def create(self, business='test', phone='0871234567', **changes):
        values = dict(first_name='Fictional', last_name='Customer', phone=phone, date_of_birth='1990-01-01', **changes)
        return self.service.create(business, CustomerInput(**values))

    def test_create_retrieve_serialization_and_restart(self):
        customer = self.create(marketing_consent=True, email='fictional@example.invalid', address='Test address', eircode='TEST')
        item = self.client.items[('test', customer.customer_id)]
        self.assertEqual(item['item_type'], 'CUSTOMER')
        for key, value in customer.model_dump(mode='json').items():
            self.assertEqual(item[key], value)
        self.assertIsInstance(item['marketing_consent'], bool)
        self.assertTrue(item['created_at'].endswith('Z'))
        restarted = CustomerService(DynamoDBCustomerRepository(self.client, TABLE))
        self.assertEqual(restarted.get('test', customer.customer_id), customer)
        self.assertTrue(self.client.calls[-1][1]['ConsistentRead'])
        self.assertEqual(self.client.calls[-1][1]['Key']['business_id'], {'S': 'test'})
        self.assertEqual(item['phone'], '+353871234567')

    def test_null_optionals_and_consent(self):
        customer = self.create()
        item = self.client.items[('test', customer.customer_id)]
        self.assertIsNone(item['email'])
        self.assertIsNone(item['consent_timestamp'])
        self.assertEqual(self.repo.get('test', customer.customer_id), customer)
        self.assertEqual(self.repo._encode(item)['email'], {'NULL': True})

    def test_business_isolation_and_duplicate_formats(self):
        customer = self.create()
        with self.assertRaises(DuplicatePhone):
            self.create(phone='+353871234567')
        other = self.create('other', '+353871234567')
        self.assertIsNone(self.repo.get('other', customer.customer_id))
        self.assertIsNone(self.repo.get('test', other.customer_id))
        self.assertEqual([c.customer_id for c in self.repo.list('test')], [customer.customer_id])
        self.assertEqual([c.customer_id for c in self.repo.list('other')], [other.customer_id])
        with self.assertRaises(CustomerNotFound):
            self.service.update('other', customer.customer_id, self.data())

    def test_list_paginates_empty_filtered_pages_and_excludes_internal_items(self):
        customer = self.create()
        self.client.page_size = 1
        # Reserved records sort before UUID keys and can yield an empty filtered page.
        self.client.items[('test', 'DOC#future')] = {'business_id': 'test', 'customer_id': 'DOC#future', 'item_type': 'DOCUMENT_METADATA'}
        self.create('other')
        self.assertEqual(self.repo.list('test'), [customer])
        queries = [params for operation, params in self.client.calls if operation == 'query']
        self.assertGreaterEqual(len(queries), 3)
        self.assertIn('ExclusiveStartKey', queries[-1])
        self.assertTrue(all(query['ConsistentRead'] for query in queries))
        self.assertIsNone(self.repo.get('test', 'PHONE#+353871234567'))
        self.assertIsNone(self.repo.get('test', 'DOC#future'))

    def test_update_preserves_immutable_fields_and_future_metadata(self):
        customer = self.create()
        self.client.items[('test', customer.customer_id)]['document_references'] = {'future': 'private-reference'}
        updated = self.service.update('test', customer.customer_id, self.data(first_name='Updated'))
        self.assertEqual(updated.first_name, 'Updated')
        self.assertEqual(self.repo.get('test', customer.customer_id), updated)
        for field in ['customer_id', 'business_id', 'qr_token', 'created_at']:
            self.assertEqual(getattr(customer, field), getattr(updated, field))
        self.assertEqual(self.client.items[('test', customer.customer_id)]['document_references'], {'future': 'private-reference'})
        actions = self.client.calls[-2][1].get('TransactItems')
        self.assertEqual([next(iter(action)) for action in actions], ['ConditionCheck', 'Update'])

    def test_phone_change_claims_new_and_releases_old_atomically(self):
        customer = self.create()
        updated = self.service.update('test', customer.customer_id, CustomerInput(**{**self.data().model_dump(), 'phone': '0867654321'}))
        self.assertEqual(updated.phone, '+353867654321')
        self.assertNotIn(('test', 'PHONE#+353871234567'), self.client.items)
        self.assertEqual(self.client.items[('test', 'PHONE#+353867654321')]['owner_customer_id'], customer.customer_id)
        transaction = [p for operation, p in self.client.calls if operation == 'transact_write_items'][-1]
        self.assertEqual([next(iter(action)) for action in transaction['TransactItems']], ['Put', 'Update', 'Delete'])
        self.create(phone='+353871234567')  # Old number is now reusable.
        with self.assertRaises(DuplicatePhone):
            self.create(phone='0867654321')

    def test_duplicate_phone_update_rolls_back_every_item(self):
        one = self.create()
        two = self.create(phone='0867654321')
        before = deepcopy(self.client.items)
        with self.assertRaises(DuplicatePhone):
            self.service.update('test', one.customer_id, CustomerInput(**{**self.data().model_dump(), 'phone': two.phone}))
        self.assertEqual(self.client.items, before)

    def test_concurrent_creates_cannot_duplicate_a_phone(self):
        def create(_):
            try:
                self.create()
                return 'created'
            except DuplicatePhone:
                return 'duplicate'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(create, range(2))), ['created', 'duplicate'])
        self.assertEqual(len(self.repo.list('test')), 1)

    def test_stale_update_rejected_before_transaction(self):
        old = self.create()
        newer = self.service.update('test', old.customer_id, self.data(first_name='Newer'))
        stale = old.model_copy(update={'first_name': 'Stale', 'updated_at': datetime.now(timezone.utc)})
        with self.assertRaises(ConcurrentModification):
            self.repo.save(stale, expected_updated_at=old.updated_at)
        self.assertEqual(self.repo.get('test', old.customer_id), newer)

    def test_update_race_between_read_and_transaction_rolls_back_locks(self):
        old = self.create()
        original = self.client.transact_write_items
        def racing_write(**params):
            self.client.items[('test', old.customer_id)]['updated_at'] = '2099-01-01T00:00:00Z'
            return original(**params)
        self.client.transact_write_items = racing_write
        with self.assertRaises(ConcurrentModification):
            self.service.update('test', old.customer_id, CustomerInput(**{**self.data().model_dump(), 'phone': '0867654321'}))
        self.assertNotIn(('test', 'PHONE#+353867654321'), self.client.items)
        self.assertIn(('test', 'PHONE#+353871234567'), self.client.items)

    def test_customer_id_collision_does_not_overwrite_record(self):
        old = self.create()
        collision = old.model_copy(update={'phone': '+353867654321'})
        with self.assertRaises(ConcurrentModification):
            self.repo.save(collision)
        self.assertEqual(self.repo.get('test', old.customer_id), old)
        self.assertNotIn(('test', 'PHONE#+353867654321'), self.client.items)

    def test_transaction_conflict_retries_same_idempotency_token(self):
        self.client.injected_errors.append(aws_error('TransactionCanceledException', ['TransactionConflict', 'None']))
        with patch('app.dynamodb_repository.time.sleep'):
            self.create()
        writes = [params for op, params in self.client.calls if op == 'transact_write_items']
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[0], writes[1])

    def test_retry_exhaustion_and_aws_failures_are_storage_errors(self):
        for error in [aws_error('AccessDeniedException'), aws_error('ResourceNotFoundException'), aws_error('TransactionCanceledException', ['ValidationError', 'None']), NoCredentialsError(), EndpointConnectionError(endpoint_url='https://test.invalid')]:
            with self.subTest(error=type(error).__name__):
                self.client.injected_errors = [error]
                with self.assertRaises(StorageUnavailable):
                    self.create()
        self.client.injected_errors = [aws_error('TransactionConflictException')] * 3
        with patch('app.dynamodb_repository.time.sleep'), self.assertRaises(StorageUnavailable):
            self.create()
        self.assertEqual(self.client.items, {})

    def test_missing_lock_is_storage_error_not_duplicate(self):
        old = self.create()
        del self.client.items[('test', 'PHONE#+353871234567')]
        with self.assertRaises(StorageUnavailable):
            self.service.update('test', old.customer_id, self.data())

    def test_duplicate_fallback_when_cancellation_reasons_are_absent(self):
        self.create()
        self.client.injected_errors.append(aws_error('TransactionCanceledException'))
        with self.assertRaises(DuplicatePhone):
            self.create(phone='+353871234567')

    def test_reads_and_bad_stored_data_fail_safely(self):
        with patch.object(self.client, 'get_item', side_effect=aws_error('AccessDeniedException')):
            with self.assertRaises(StorageUnavailable):
                self.repo.get('test', 'missing')
        with patch.object(self.client, 'query', side_effect=EndpointConnectionError(endpoint_url='https://test.invalid')):
            with self.assertRaises(StorageUnavailable):
                self.repo.list('test')
        self.client.items[('test', 'corrupt')] = {'business_id': 'test', 'customer_id': 'corrupt', 'item_type': 'CUSTOMER'}
        with self.assertRaises(StorageUnavailable):
            self.repo.get('test', 'corrupt')

    def test_actual_boto3_client_accepts_transaction_and_query_shapes(self):
        customer = self.create()
        calls = [params for op, params in self.client.calls if op == 'transact_write_items']
        # Explicit fake credentials prevent use of local profiles or credential providers.
        client = boto3.client('dynamodb', region_name='eu-west-1', aws_access_key_id='test', aws_secret_access_key='test')
        with Stubber(client) as stubber:
            stubber.add_response('transact_write_items', {}, calls[0])
            with patch('app.dynamodb_repository.uuid4', return_value=calls[0]['ClientRequestToken']):
                DynamoDBCustomerRepository(client, TABLE).save(customer)
            self.repo.list('test')
            query = [params for op, params in self.client.calls if op == 'query'][-1]
            stubber.add_response('query', {'Items': [self.repo._encode(self.client.items[('test', customer.customer_id)])]}, query)
            self.assertEqual(DynamoDBCustomerRepository(client, TABLE).list('test'), [customer])
            stubber.assert_no_pending_responses()


async def asgi_get(app, path):
    messages = []
    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    async def send(message):
        messages.append(message)
    await app({'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'GET', 'scheme': 'http', 'path': path, 'raw_path': path.encode(), 'query_string': b'', 'headers': [(b'authorization', b'Bearer fixture')], 'server': ('test', 80), 'client': ('test', 1)}, receive, send)
    status = next(m['status'] for m in messages if m['type'] == 'http.response.start')
    body = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
    return status, json.loads(body)


class StorageHTTPErrorTests(unittest.TestCase):
    def test_application_errors_do_not_expose_aws_details(self):
        # Avoid environment loading during module-level app creation.
        with patch('app.config.build_repository') as factory:
            from main import create_app
        for error, expected in [(StorageUnavailable('raw AWS details'), 503), (ConcurrentModification('raw AWS details'), 409), (DuplicatePhone('raw AWS details'), 409)]:
            repository = Mock()
            repository.list.side_effect = error
            from app.auth import Role, UserContext
            verifier = Mock()
            verifier.verify.return_value = UserContext('fixture', None, 'test', ('Owner',), Role.OWNER)
            status, body = asyncio.run(asgi_get(create_app(repository, verifier), '/customers'))
            self.assertEqual(status, expected)
            self.assertNotIn('raw AWS', json.dumps(body))
