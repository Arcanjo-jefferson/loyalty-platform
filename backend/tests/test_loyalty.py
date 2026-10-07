import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
import unittest
from unittest.mock import Mock, patch
import boto3
from botocore.stub import Stubber
from app.auth import Role, UserContext
from app.models import CustomerInput
from app.repository import InMemoryCustomerRepository, DuplicateVisit, InactiveCustomer, DuplicateQR, ConcurrentModification, StorageUnavailable
from app.dynamodb_repository import DynamoDBCustomerRepository
from app.service import CustomerService, CustomerNotFound
from app.voucher_rules import rewards_for_visit
from app.loyalty_service import LoyaltyService
from fake_dynamodb import FakeDynamoDB
from test_auth import request
from scripts.backfill_qr_locks import backfill


def data(phone='0871234567', **changes):
    return CustomerInput(first_name='Fictional', last_name='Customer', phone=phone, date_of_birth='1990-01-01', **changes)


class LoyaltyRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDynamoDB(page_size=1)
        self.repo = DynamoDBCustomerRepository(self.db, 'fixture-table')
        self.customers = CustomerService(self.repo)
        self.customer = self.customers.create('tenant-a', data())
        self.user = UserContext('trusted-subject', None, 'tenant-a', (), Role.STAFF)
        self.now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        self.service = LoyaltyService(self.customers, lambda: self.now)

    def test_qr_lookup_is_scoped_active_and_does_not_record(self):
        result = self.service.lookup('tenant-a', self.customer.qr_token)
        self.assertEqual(result['customer'], self.customer)
        self.assertEqual(result['total_visits'], 0)
        self.assertEqual(self.repo.visits('tenant-a', self.customer.customer_id), [])
        for business, token in [('tenant-b', self.customer.qr_token), ('tenant-a', 'unknown-token-value')]:
            with self.assertRaises(CustomerNotFound): self.service.lookup(business, token)
        self.customers.update('tenant-a', self.customer.customer_id, data(status='inactive'))
        with self.assertRaises(CustomerNotFound): self.service.lookup('tenant-a', self.customer.qr_token)
        with self.assertRaises(InactiveCustomer): self.service.confirm(self.user, self.customer.customer_id)

    def test_progress_six_visits_and_history_retained(self):
        for total in range(1, 7):
            result = self.service.confirm(self.user, self.customer.customer_id)
            self.assertEqual(result['total_visits'], total)
            self.assertEqual(result['progress'], total % 5)
            self.assertEqual(result['visits_until_reward'], 5 - total % 5)
            self.assertEqual(result['reward_earned'], total == 5)
            self.assertEqual(result['visit'].recorded_by, 'trusted-subject')
            self.assertEqual(result['visit'].visit_number, total)
            self.now += timedelta(days=1)
        history = self.service.history('tenant-a', self.customer.customer_id)
        self.assertEqual(len(history['visits']), 6)
        self.assertEqual([v.visit_number for v in history['visits']], list(range(1, 7)))
        self.assertEqual(history['total_visits'], 6)
        with self.assertRaises(CustomerNotFound): self.service.history('tenant-b', self.customer.customer_id)
        self.assertFalse(any(call[0] == 'scan' for call in self.db.calls))
        self.assertEqual(len([item for item in self.db.items.values() if item.get('item_type') == 'VISIT']), 6)

    def test_corrupt_visit_state_fails_closed(self):
        key = ('tenant-a', self.customer.customer_id)
        for count in ['invalid', True, -1, Decimal('1.5')]:
            self.db.items[key]['loyalty_total_visits'] = count
            with self.assertRaises(StorageUnavailable):
                self.service.confirm(self.user, self.customer.customer_id)
        self.assertEqual(self.repo.visits('tenant-a', self.customer.customer_id), [])

    def test_same_date_rejection_preserves_progress_and_history(self):
        self.now = datetime(2026, 10, 6, 8, tzinfo=timezone.utc)
        first = self.service.confirm(self.user, self.customer.customer_id)
        before = deepcopy(self.db.items)
        self.now = datetime(2026, 10, 6, 21, tzinfo=timezone.utc)
        with self.assertRaises(DuplicateVisit): self.service.confirm(self.user, self.customer.customer_id)
        self.assertEqual(self.db.items, before)
        self.assertEqual(self.service.history('tenant-a', self.customer.customer_id)['progress'], 1)
        self.assertEqual(str(first['visit'].local_visit_date), '2026-10-06')
        self.assertEqual(first['visit'].business_timezone, 'Europe/Dublin')
        self.assertEqual(first['visit'].visited_at.utcoffset(), timedelta(0))
        self.now += timedelta(days=1)
        self.assertEqual(self.service.confirm(self.user, self.customer.customer_id)['total_visits'], 2)

    def test_midnight_and_dst_calendar_boundaries_both_adapters(self):
        cases = [
            ('2026-10-06T22:55:00+00:00', '2026-10-06T23:05:00+00:00', True),
            ('2026-03-28T23:55:00+00:00', '2026-03-29T00:05:00+00:00', True),
            ('2026-03-29T00:55:00+00:00', '2026-03-29T01:05:00+00:00', False),
            ('2026-03-29T22:55:00+00:00', '2026-03-29T23:05:00+00:00', True),
            ('2026-10-25T00:30:00+00:00', '2026-10-25T01:30:00+00:00', False),
            ('2026-10-25T23:55:00+00:00', '2026-10-26T00:05:00+00:00', True),
        ]
        for adapter in ['memory', 'dynamodb']:
            for first, second, accepted in cases:
                with self.subTest(adapter=adapter, first=first, second=second):
                    repo = InMemoryCustomerRepository() if adapter == 'memory' else DynamoDBCustomerRepository(FakeDynamoDB(page_size=1), 'fixture-table')
                    customers = CustomerService(repo); customer = customers.create('tenant-a', data())
                    now = datetime.fromisoformat(first)
                    service = LoyaltyService(customers, lambda: now)
                    service.confirm(self.user, customer.customer_id)
                    now = datetime.fromisoformat(second)
                    if accepted:
                        self.assertEqual(service.confirm(self.user, customer.customer_id)['total_visits'], 2)
                    else:
                        with self.assertRaises(DuplicateVisit): service.confirm(self.user, customer.customer_id)
                        self.assertEqual(repo.total_visits('tenant-a', customer.customer_id), 1)
                        self.assertEqual(len(repo.visits('tenant-a', customer.customer_id)), 1)

    def test_existing_visit_without_local_metadata_blocks_same_date_without_backfill(self):
        self.service.confirm(self.user, self.customer.customer_id)
        for item in self.db.items.values():
            if item.get('item_type') == 'VISIT':
                item.pop('local_visit_date'); item.pop('business_timezone')
        before = deepcopy(self.db.items)
        self.now += timedelta(hours=8)
        with self.assertRaises(DuplicateVisit): self.service.confirm(self.user, self.customer.customer_id)
        self.assertEqual(self.db.items, before)
        history = self.service.history('tenant-a', self.customer.customer_id)
        self.assertEqual(str(history['visits'][0].local_visit_date), '2026-10-06')
        self.assertEqual(history['total_visits'], 1)

    def test_simultaneous_confirmations_only_commit_one_visit(self):
        barrier = Barrier(2)
        original = self.repo.visits
        def concurrent_read(*args):
            result = original(*args)
            if not result: barrier.wait(timeout=5)
            return result
        def confirm(_):
            try: self.service.confirm(self.user, self.customer.customer_id); return 'created'
            except DuplicateVisit: return 'duplicate'
        with patch.object(self.repo, 'visits', side_effect=concurrent_read), ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(confirm, range(2))), ['created', 'duplicate'])
        self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 1)
        self.assertEqual(len(self.repo.visits('tenant-a', self.customer.customer_id)), 1)

    def test_inactive_status_race_is_guarded_inside_transaction(self):
        original = self.db.transact_write_items
        def write(**kwargs):
            self.db.items[('tenant-a', self.customer.customer_id)]['status'] = 'inactive'
            return original(**kwargs)
        with patch.object(self.db, 'transact_write_items', side_effect=write), self.assertRaises(InactiveCustomer):
            self.service.confirm(self.user, self.customer.customer_id)
        self.assertEqual(self.repo.visits('tenant-a', self.customer.customer_id), [])

    def test_internal_rows_phone_uniqueness_and_media_survive_updates(self):
        self.repo.save_media('tenant-a', self.customer.customer_id, 'profile', {'revision': 'fixture', 'key': 'private-reference'}, expected_revision=None)
        self.service.confirm(self.user, self.customer.customer_id)
        self.assertEqual(self.repo.list('tenant-a'), [self.customer])
        for key in self.db.items:
            if key[1].startswith(('QR#', 'VISIT#')): self.assertIsNone(self.repo.get(*key))
        from app.repository import DuplicatePhone
        with self.assertRaises(DuplicatePhone): self.customers.create('tenant-a', data())
        updated = self.customers.update('tenant-a', self.customer.customer_id, data('0851234567'))
        self.assertEqual(self.repo.get_media('tenant-a', updated.customer_id, 'profile')['key'], 'private-reference')
        self.assertEqual(self.repo.total_visits('tenant-a', updated.customer_id), 1)
        self.assertEqual(self.repo.find_active_by_qr('tenant-a', updated.qr_token), updated)
        self.customers.create('tenant-a', data())  # Old phone released, QR stays immutable.

    def test_qr_collision_rolls_back_customer_and_phone(self):
        collision = self.customer.model_copy(update={'customer_id': 'another-customer', 'phone': '+353851234567'})
        before = deepcopy(self.db.items)
        with self.assertRaises(DuplicateQR): self.repo.save(collision)
        self.assertEqual(self.db.items, before)
        other = collision.model_copy(update={'business_id': 'tenant-b'})
        self.repo.save(other)  # Index uniqueness is per business.

    def test_legacy_backfill_dry_run_apply_idempotency_and_conflicts(self):
        key = ('tenant-a', 'QR#' + self.customer.qr_token)
        del self.db.items[key]
        original_token = self.customer.qr_token
        self.assertEqual(backfill(self.repo, 'tenant-a'), {'customers': 1, 'missing': 1, 'applied': False})
        self.assertNotIn(key, self.db.items)
        with self.assertRaises(CustomerNotFound): self.service.lookup('tenant-a', original_token)
        backfill(self.repo, 'tenant-a', True); backfill(self.repo, 'tenant-a', True)
        self.assertEqual(self.service.lookup('tenant-a', original_token)['customer'].qr_token, original_token)
        self.db.items[key]['owner_customer_id'] = 'different-owner'
        before = deepcopy(self.db.items)
        with self.assertRaises(DuplicateQR): backfill(self.repo, 'tenant-a', True)
        self.assertEqual(self.db.items, before)
        with self.assertRaises(DuplicateQR): self.repo.ensure_qr_lock(self.customer)

    def test_backfill_rejects_duplicate_tokens_and_changed_customer(self):
        self.db.items[('tenant-a', 'legacy-duplicate')] = {**self.db.items[('tenant-a', self.customer.customer_id)], 'customer_id': 'legacy-duplicate'}
        before = deepcopy(self.db.items)
        with self.assertRaises(DuplicateQR): backfill(self.repo, 'tenant-a', True)
        self.assertEqual(self.db.items, before)
        self.db.items[('tenant-a', self.customer.customer_id)]['qr_token'] = 'changed-token-fixture'
        with self.assertRaises(ConcurrentModification): self.repo.ensure_qr_lock(self.customer)

    def test_sdk_accepts_visit_and_backfill_transaction_shapes(self):
        result = self.service.confirm(self.user, self.customer.customer_id)
        write = [params for operation, params in self.db.calls if operation == 'transact_write_items'][-1]
        item_before = self.customer.model_dump(mode='json') | {'item_type': 'CUSTOMER'}
        client = boto3.client('dynamodb', region_name='eu-west-1', aws_access_key_id='fixture', aws_secret_access_key='fixture')
        adapter = DynamoDBCustomerRepository(client, 'fixture-table')
        with Stubber(client) as stub:
            stub.add_response('get_item', {'Item': adapter._encode(item_before)}, {'TableName': 'fixture-table', 'Key': adapter._key('tenant-a', self.customer.customer_id), 'ConsistentRead': True})
            query = [params for operation, params in self.db.calls if operation == 'query'][-1]
            stub.add_response('query', {'Items': []}, query)
            stub.add_response('transact_write_items', {}, write)
            with patch('app.loyalty_repository.uuid4', return_value=write['ClientRequestToken']):
                saved = adapter.record_visit(result['visit'], rewards_for_visit)
            self.assertEqual(saved[2], 1)
            self.repo.ensure_qr_lock(self.customer)
            write = [params for operation, params in self.db.calls if operation == 'transact_write_items'][-1]
            stub.add_response('transact_write_items', {}, write)
            with patch('app.loyalty_repository.uuid4', return_value=write['ClientRequestToken']): adapter.ensure_qr_lock(self.customer)
            stub.assert_no_pending_responses()

    def test_memory_adapter_matches_daily_progress_and_isolation(self):
        repository = InMemoryCustomerRepository(); customers = CustomerService(repository)
        customer = customers.create('tenant-a', data())
        service = LoyaltyService(customers, lambda: self.now)
        self.assertEqual(service.lookup('tenant-a', customer.qr_token)['progress'], 0)
        service.confirm(self.user, customer.customer_id)
        with self.assertRaises(DuplicateVisit): service.confirm(self.user, customer.customer_id)
        self.assertIsNone(repository.find_active_by_qr('tenant-b', customer.qr_token))
        for number in range(2, 7):
            self.now += timedelta(days=1)
            result = service.confirm(self.user, customer.customer_id)
            self.assertEqual(result['progress'], number % 5)
        self.assertEqual(len(service.history('tenant-a', customer.customer_id)['visits']), 6)


class LoyaltyAPITests(unittest.TestCase):
    def setUp(self):
        with patch('app.config.build_repository'), patch('app.media_storage.build_media_storage'):
            from main import create_app
        self.repository = InMemoryCustomerRepository(); self.verifier = Mock()
        self.user = UserContext('trusted-cognito-subject', None, 'tenant-a', (), Role.STAFF)
        self.verifier.verify.return_value = self.user
        self.app = create_app(self.repository, self.verifier)
        self.customer = self.app.state.customer_service.create('tenant-a', data())
        self.path = '/customers/' + self.customer.customer_id + '/visits'
    def call(self, method='GET', path=None, data=None, token='fixture', query=''):
        return asyncio.run(request(self.app, method, path or self.path, token=token, data=data, query=query))

    def test_authentication_and_untrusted_identity_fields(self):
        for method, path, body in [('POST', '/loyalty/lookup', {'qr_token': self.customer.qr_token}), ('POST', self.path, {}), ('GET', self.path, None)]:
            self.assertEqual(self.call(method, path, body, token=None)[0], 401)
        for body in [{'recorded_by': 'attacker'}, {'business_id': 'tenant-b'}, {'visited_at': '2026-01-01'}, {'customer_id': 'other'}]:
            self.assertEqual(self.call('POST', data=body)[0], 422)
        self.assertEqual(self.call('POST', data={}, query='business_id=tenant-b')[0], 403)
        self.assertEqual(self.call('POST', '/loyalty/lookup', {'qr_token': self.customer.qr_token, 'business_id': 'tenant-b'})[0], 422)

    def test_all_roles_lookup_confirm_and_history(self):
        for index, role in enumerate(Role):
            self.verifier.verify.return_value = UserContext('trusted-' + role.value, None, 'tenant-a', (), role)
            self.app.state.loyalty_service.clock = lambda: datetime(2026, 10, 6 + index, 12, tzinfo=timezone.utc)
            code, lookup = self.call('POST', '/loyalty/lookup', {'qr_token': self.customer.qr_token})
            self.assertEqual(code, 200)
            self.assertEqual(lookup['customer']['customer_id'], self.customer.customer_id)
            code, result = self.call('POST', data={})
            self.assertEqual(code, 201)
            self.assertEqual(result['visit']['recorded_by'], 'trusted-' + role.value)
            self.assertEqual(self.call()[0], 200)
        self.assertEqual(self.call()[1]['total_visits'], 3)

    def test_duplicate_inactive_unknown_and_cross_tenant(self):
        self.assertEqual(self.call('POST', data={})[0], 201)
        code, error = self.call('POST', data={})
        self.assertEqual(code, 409)
        self.assertEqual(error['detail'], 'A loyalty visit has already been recorded for this customer today.')
        self.assertEqual(self.call()[1]['total_visits'], 1)
        self.verifier.verify.return_value = UserContext('other', None, 'tenant-b', (), Role.OWNER)
        self.assertEqual(self.call('POST', '/loyalty/lookup', {'qr_token': self.customer.qr_token})[0], 404)
        self.assertEqual(self.call()[0], 404)
        self.assertEqual(self.call('POST', data={})[0], 404)
        self.verifier.verify.return_value = self.user
        self.app.state.customer_service.update('tenant-a', self.customer.customer_id, data(status='inactive'))
        self.assertEqual(self.call('POST', data={})[0], 409)
        self.assertEqual(self.call('POST', '/loyalty/lookup', {'qr_token': self.customer.qr_token})[0], 404)
        self.assertEqual(self.call('POST', '/loyalty/lookup', {'qr_token': 'unknown-valid-token'})[0], 404)

