import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from threading import Barrier
import unittest
from unittest.mock import Mock, patch
from PIL import Image
import qrcode
import boto3
from botocore.stub import Stubber
from app.auth import Role, UserContext, user_from_claims, InvalidMembership
from app.repository import InMemoryCustomerRepository, ConcurrentModification
from app.dynamodb_repository import DynamoDBCustomerRepository
from app.service import CustomerService, CustomerNotFound
from app.loyalty_service import LoyaltyService
from app.qr_repository import QRNotFound, PUBLIC_PARTITION
from app.qr_service import QRService, qr_png
from fake_dynamodb import FakeDynamoDB
from test_loyalty import data
from test_auth import request


class QRRepositoryTests(unittest.TestCase):
    memory = False
    def setUp(self):
        self.db = FakeDynamoDB(page_size=1)
        self.repo = InMemoryCustomerRepository() if self.memory else DynamoDBCustomerRepository(self.db, 'fixture-table')
        self.customers = CustomerService(self.repo)
        self.customer = self.customers.create('tenant-a', data())
        self.qr = QRService(self.customers)
    def test_link_stable_preserves_token_and_public_payload_is_only_token(self):
        first = self.qr.link('tenant-a', self.customer.customer_id)
        second = self.qr.link('tenant-a', self.customer.customer_id)
        self.assertEqual(first, second)
        self.assertEqual(first['qr_token'], self.customer.qr_token)
        self.assertEqual(len(first['public_reference']), 43)
        self.assertEqual(self.repo.public_qr_token(first['public_reference']), self.customer.qr_token)
        for pii in [self.customer.customer_id, self.customer.phone, self.customer.first_name, 'tenant-a']:
            self.assertNotIn(pii, first['public_reference'])
        self.assertEqual(self.repo.list('tenant-a'), [self.customer])
        self.assertFalse(any(op == 'scan' for op, _ in self.db.calls))
    def test_regeneration_invalidates_both_old_credentials_and_keeps_rewards_media(self):
        user = UserContext('trusted-sub', None, 'tenant-a', (), Role.OWNER)
        now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
        loyalty = LoyaltyService(self.customers, lambda: now)
        for _ in range(5): loyalty.confirm(user, self.customer.customer_id); now += timedelta(days=1)
        self.repo.save_media('tenant-a', self.customer.customer_id, 'profile', {'revision': 'fixture', 'key': 'private'}, expected_revision=None)
        before = self.qr.link('tenant-a', self.customer.customer_id)
        after = self.qr.regenerate('tenant-a', self.customer.customer_id, before['qr_token'])
        self.assertNotEqual(after, before)
        self.assertIsNone(self.repo.find_active_by_qr('tenant-a', before['qr_token']))
        with self.assertRaises(QRNotFound): self.repo.public_qr_token(before['public_reference'])
        self.assertEqual(self.repo.public_qr_token(after['public_reference']), after['qr_token'])
        self.assertEqual(self.repo.find_active_by_qr('tenant-a', after['qr_token']).customer_id, self.customer.customer_id)
        self.assertIsNone(self.repo.find_active_by_qr('tenant-b', after['qr_token']))
        self.assertEqual(len(self.repo.visits('tenant-a', self.customer.customer_id)), 5)
        self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 5)
        self.assertEqual(len(self.repo.vouchers('tenant-a', self.customer.customer_id)), 1)
        self.assertEqual(self.repo.get_media('tenant-a', self.customer.customer_id, 'profile')['key'], 'private')
        customer = self.repo.get('tenant-a', self.customer.customer_id)
        for key in type(self.customer).model_fields:
            if key not in ['qr_token', 'updated_at']: self.assertEqual(getattr(customer, key), getattr(self.customer, key))
    def test_tenant_scope_inactive_public_and_stale_rotation(self):
        link = self.qr.link('tenant-a', self.customer.customer_id)
        with self.assertRaises(CustomerNotFound): self.qr.link('tenant-b', self.customer.customer_id)
        with self.assertRaises(CustomerNotFound): self.qr.regenerate('tenant-b', self.customer.customer_id, link['qr_token'])
        self.qr.regenerate('tenant-a', self.customer.customer_id, link['qr_token'])
        with self.assertRaises(ConcurrentModification): self.qr.regenerate('tenant-a', self.customer.customer_id, link['qr_token'])
        current = self.qr.link('tenant-a', self.customer.customer_id)
        self.customers.update('tenant-a', self.customer.customer_id, data(status='inactive'))
        with self.assertRaises(QRNotFound): self.repo.public_qr_token(current['public_reference'])
    def test_concurrent_initial_links_converge_and_rotation_has_one_winner(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            links = list(pool.map(lambda _: self.qr.link('tenant-a', self.customer.customer_id), range(2)))
        self.assertEqual(links[0], links[1])
        barrier = Barrier(2)
        def regenerate(_):
            barrier.wait(timeout=5)
            try: self.qr.regenerate('tenant-a', self.customer.customer_id, links[0]['qr_token']); return 'success'
            except ConcurrentModification: return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(regenerate, range(2))), ['conflict', 'success'])


class MemoryQRTests(QRRepositoryTests):
    memory = True


class QRStorageTests(QRRepositoryTests):
    def test_public_directory_cannot_be_authenticated_business(self):
        with self.assertRaises(InvalidMembership):
            user_from_claims({'sub': 'fixture', 'custom:business_id': PUBLIC_PARTITION, 'cognito:groups': ['owner']})
    def test_real_sdk_accepts_link_and_regeneration_transaction_shapes(self):
        initial = self.qr.link('tenant-a', self.customer.customer_id)
        self.qr.regenerate('tenant-a', self.customer.customer_id, initial['qr_token'])
        writes = [params for op, params in self.db.calls if op == 'transact_write_items'][-2:]
        client = boto3.client('dynamodb', region_name='eu-west-1', aws_access_key_id='fixture', aws_secret_access_key='fixture')
        with Stubber(client) as stub:
            for params in writes:
                stub.add_response('transact_write_items', {}, params)
                client.transact_write_items(**params)
            stub.assert_no_pending_responses()


class QRImageTests(unittest.TestCase):
    def test_png_matches_real_qr_matrix_and_quiet_zone_for_exact_scanner_payload(self):
        token = 'fixture-opaque-token-that-contains-no-personal-data'
        code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
        code.add_data(token, optimize=0); code.make(fit=True)
        self.assertEqual(code.data_list[0].data, token.encode())
        image = Image.open(BytesIO(qr_png(token))).convert('L')
        matrix = code.get_matrix()
        self.assertEqual(image.size, (len(matrix) * 8, len(matrix) * 8))
        for y, row in enumerate(matrix):
            for x, black in enumerate(row): self.assertEqual(image.getpixel((x * 8 + 4, y * 8 + 4)), 0 if black else 255)


class QRAPITests(unittest.TestCase):
    def setUp(self):
        with patch('app.config.build_repository'), patch('app.media_storage.build_media_storage'):
            from main import create_app
        self.repo = InMemoryCustomerRepository(); self.verifier = Mock()
        self.user = UserContext('trusted-sub', None, 'tenant-a', (), Role.STAFF)
        self.verifier.verify.return_value = self.user
        self.app = create_app(self.repo, self.verifier)
        self.customer = self.app.state.customer_service.create('tenant-a', data())
        self.prefix = f'/customers/{self.customer.customer_id}/qr'
    def call(self, method, path, body=None, token='fixture'):
        return asyncio.run(request(self.app, method, path, token=token, data=body))
    def test_staff_can_recover_but_cannot_regenerate_and_send_is_honest(self):
        code, link = self.call('POST', self.prefix + '/link', {})
        self.assertEqual(code, 200)
        self.assertEqual(self.call('POST', self.prefix + '/regenerate', {'expected_qr_token': link['qr_token'], 'confirmed': True})[0], 403)
        self.assertEqual(self.call('POST', self.prefix + '/send', {})[0], 501)
        self.assertEqual(self.call('POST', self.prefix + '/link', {}, token=None)[0], 401)
        self.assertEqual(self.call('GET', self.prefix + '/image', token=None)[0], 401)
    def test_owner_manager_regenerate_confirmation_and_business_scope(self):
        for role in [Role.OWNER, Role.MANAGER]:
            self.verifier.verify.return_value = UserContext('trusted-sub', None, 'tenant-a', (), role)
            _, link = self.call('POST', self.prefix + '/link', {})
            body = {'expected_qr_token': link['qr_token'], 'confirmed': False}
            self.assertEqual(self.call('POST', self.prefix + '/regenerate', body)[0], 422)
            body['confirmed'] = True
            self.assertEqual(self.call('POST', self.prefix + '/regenerate', body)[0], 200)
        self.verifier.verify.return_value = UserContext('trusted-sub', None, 'tenant-b', (), Role.OWNER)
        self.assertEqual(self.call('POST', self.prefix + '/link', {})[0], 404)
    def test_customer_directory_is_scoped_for_all_roles(self):
        other = self.app.state.customer_service.create('tenant-b', data())
        for role in Role:
            self.verifier.verify.return_value = UserContext('fixture', None, 'tenant-a', (), role)
            status, customers = self.call('GET', '/customers')
            self.assertEqual(status, 200)
            self.assertEqual([c['customer_id'] for c in customers], [self.customer.customer_id])
            self.assertNotIn(other.customer_id, str(customers))

    def test_public_endpoint_binary_only_no_auth_or_customer_fields(self):
        _, link = self.call('POST', self.prefix + '/link', {})
        # ASGI helper assumes JSON; use raw ASGI messages to inspect binary output.
        async def raw():
            messages = []
            async def receive(): return {'type': 'http.request', 'body': b'', 'more_body': False}
            async def send(message): messages.append(message)
            await self.app({'type': 'http', 'http_version': '1.1', 'method': 'GET', 'path': f"/public/qr/{link['public_reference']}/image", 'query_string': b'', 'headers': [], 'scheme': 'http', 'server': ('test', 80), 'client': ('test', 1)}, receive, send)
            return messages
        messages = asyncio.run(raw())
        self.assertEqual(messages[0]['status'], 200)
        self.assertIn((b'cache-control', b'no-store'), messages[0]['headers'])
        payload = b''.join(m.get('body', b'') for m in messages)
        self.assertTrue(payload.startswith(b'\x89PNG'))
        self.assertNotIn(b'first_name', payload)
        self.assertEqual(self.call('GET', '/public/qr/invalid/image', token=None)[0], 404)
