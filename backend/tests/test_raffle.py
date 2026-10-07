"""Raffle transaction/security tests: local fakes/stubs, never real AWS."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
from threading import Barrier
import unittest
from unittest.mock import Mock, patch
import boto3
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from app.auth import Role, UserContext
from app.models import Visit, RaffleEntry
from pydantic import ValidationError
from app.repository import InMemoryCustomerRepository, DuplicateVisit, InactiveCustomer, StorageUnavailable, ConcurrentModification
from app.dynamodb_repository import DynamoDBCustomerRepository
from app.service import CustomerService, CustomerNotFound
from app.loyalty_service import LoyaltyService
from app.raffle import RaffleService, raffle_for_visit, raffle_key, raffle_date_key
from app.qr_service import QRService
from app.voucher_service import VoucherService
from app.visit_dates import normalize_visit
from fake_dynamodb import FakeDynamoDB
from test_vouchers import data
from test_auth import request


class RaffleTests(unittest.TestCase):
    memory = False
    def setUp(self):
        self.db = FakeDynamoDB(page_size=1)
        self.repo = InMemoryCustomerRepository() if self.memory else DynamoDBCustomerRepository(self.db, 'fixture-table')
        self.customers = CustomerService(self.repo)
        self.customer = self.customers.create('tenant-a', data())
        self.user = UserContext('trusted-cognito-subject', None, 'tenant-a', (), Role.STAFF)
        self.now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
        self.loyalty = LoyaltyService(self.customers, lambda: self.now)
        self.raffle = RaffleService(self.customers)
    def confirm(self): return self.loyalty.confirm(self.user, self.customer.customer_id)
    def entries(self): return self.raffle.history('tenant-a', self.customer.customer_id)

    def seed_history(self, count):
        # Explicit old-schema fixtures; no application writes or automatic backfill.
        for number in range(1, count + 1):
            visit = normalize_visit(Visit(business_id='tenant-a', visit_id=f'legacy-{number}',
                customer_id=self.customer.customer_id, visited_at=self.now - timedelta(days=count + 1 - number),
                recorded_by='historical-recorder', visit_number=number))
            if self.memory: self.repo._visits[('tenant-a', visit.visit_id)] = visit
            else:
                key = f'VISIT#{self.customer.customer_id}#{visit.visit_id}'
                self.db.items[('tenant-a', key)] = {**visit.model_dump(mode='json'), 'customer_id': key,
                    'owner_customer_id': self.customer.customer_id, 'item_type': 'VISIT'}
        if not self.memory: self.db.items[('tenant-a', self.customer.customer_id)]['loyalty_total_visits'] = count

    def test_normal_visit_exactly_one_entry_correct_trusted_fields_no_pii(self):
        result = self.confirm(); entry = result['raffle_entry']
        self.assertEqual(self.entries(), [entry])
        self.assertEqual(entry.visit_id, result['visit'].visit_id)
        self.assertEqual(entry.raffle_entry_id, entry.visit_id)
        self.assertEqual(entry.customer_id, self.customer.customer_id)
        self.assertEqual(entry.business_id, self.user.business_id)
        self.assertEqual(entry.recorded_by, self.user.subject)
        self.assertEqual(entry.created_at, result['visit'].visited_at)
        self.assertEqual(entry.visit_number, 1); self.assertEqual(entry.item_type, 'RAFFLE_ENTRY')
        self.assertFalse(set(entry.model_dump()) & {'phone', 'first_name', 'last_name', 'email', 'date_of_birth', 'qr_token'})
        self.assertEqual(self.raffle.for_date('tenant-a', entry.raffle_date), [entry])
        self.assertEqual(self.repo.list('tenant-a'), [self.customer])

    def test_entry_is_immutable_and_invalid_timestamp_date_identity_are_rejected(self):
        entry = self.confirm()['raffle_entry']
        with self.assertRaises(ValidationError): entry.created_at = self.now + timedelta(days=1)
        for changes in [{'created_at': self.now.replace(tzinfo=None)},
                        {'raffle_date': date(2025, 1, 1)}, {'raffle_entry_id': 'unrelated'}]:
            with self.assertRaises(ValidationError):
                RaffleEntry.model_validate(entry.model_dump() | changes)

    def test_lookup_duplicate_and_retry_create_no_extra_entries(self):
        self.loyalty.lookup('tenant-a', self.customer.qr_token); self.assertEqual(self.entries(), [])
        result = self.confirm()
        for operation in [self.confirm, lambda: self.repo.record_visit(result['visit'])]:
            with self.assertRaises(DuplicateVisit): operation()
        self.assertEqual(self.entries(), [result['raffle_entry']])
        self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 1)
        self.assertEqual(len(self.repo.visits('tenant-a', self.customer.customer_id)), 1)

    def test_inactive_and_other_business_create_nothing(self):
        with self.assertRaises(CustomerNotFound): self.raffle.history('tenant-b', self.customer.customer_id)
        self.assertEqual(self.raffle.for_date('tenant-b', self.now.date()), [])
        self.customers.update('tenant-a', self.customer.customer_id, data(status='inactive'))
        with self.assertRaises(InactiveCustomer): self.confirm()
        self.assertEqual(self.entries(), []); self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 0)

    def test_history_and_date_query_paginate_and_isolate_customers(self):
        other = self.customers.create('tenant-a', data(phone='0831234567'))
        third = self.customers.create('tenant-b', data())
        first = self.confirm()['raffle_entry']
        self.loyalty.confirm(self.user, other.customer_id)
        self.loyalty.confirm(UserContext('other-sub', None, 'tenant-b', (), Role.OWNER), third.customer_id)
        self.now += timedelta(days=1); second = self.confirm()['raffle_entry']
        self.assertEqual(self.entries(), [second, first])
        self.assertEqual(len(self.raffle.for_date('tenant-a', first.raffle_date)), 2)
        self.assertEqual(len(self.raffle.for_date('tenant-b', first.raffle_date)), 1)
        self.assertEqual(self.raffle.for_date('tenant-a', date(2025, 1, 1)), [])
        self.assertFalse(any(operation == 'scan' for operation, _ in self.db.calls))

    def test_historical_visits_not_backfilled_fifth_one_raffle_and_loyalty_voucher(self):
        self.seed_history(4); self.assertEqual(self.entries(), [])
        self.loyalty.history('tenant-a', self.customer.customer_id)
        self.loyalty.lookup('tenant-a', self.customer.qr_token); self.assertEqual(self.entries(), [])
        result = self.confirm()
        self.assertEqual(result['total_visits'], 5); self.assertEqual(result['progress'], 0)
        self.assertEqual([v.type for v in result['vouchers']], ['LOYALTY_10'])
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(len(self.repo.visits('tenant-a', self.customer.customer_id)), 5)

    def test_birthday_one_entry_and_birthday_voucher(self):
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth='1990-10-07'))
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        result = self.confirm()
        self.assertEqual([v.type for v in result['vouchers']], ['BIRTHDAY_20'])
        self.assertEqual(self.entries(), [result['raffle_entry']])

    def test_fifth_and_birthday_one_entry_both_vouchers(self):
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth='1990-10-07'))
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc); self.seed_history(4)
        result = self.confirm()
        self.assertEqual({v.type for v in result['vouchers']}, {'LOYALTY_10', 'BIRTHDAY_20'})
        self.assertEqual(self.entries(), [result['raffle_entry']])
        for voucher in result['vouchers']: self.assertEqual(voucher.qualifying_visit_id, result['raffle_entry'].visit_id)

    def test_redemption_and_qr_regeneration_create_no_entries(self):
        self.seed_history(4); result = self.confirm(); before = self.entries()
        voucher = result['vouchers'][0]
        VoucherService(self.customers, lambda: self.now).redeem(self.user, self.customer.customer_id, voucher.voucher_id)
        qr = QRService(self.customers); qr.link('tenant-a', self.customer.customer_id)
        qr.regenerate('tenant-a', self.customer.customer_id, self.customer.qr_token)
        self.assertEqual(self.entries(), before)
        self.assertEqual(len(self.repo.visits('tenant-a', self.customer.customer_id)), 5)

    def test_dublin_midnight_dst_and_utc_creation_timestamp(self):
        cases = [('2026-10-06T22:55:00+00:00', '2026-10-06'), ('2026-10-06T23:05:00+00:00', '2026-10-07'),
                 ('2026-03-29T23:05:00+00:00', '2026-03-30'), ('2026-10-25T00:30:00+00:00', '2026-10-25'),
                 ('2026-10-25T01:30:00+00:00', '2026-10-25')]
        for index, (timestamp, expected) in enumerate(cases):
            customer = self.customers.create('tenant-a', data(phone=f'087123455{index}'))
            self.now = datetime.fromisoformat(timestamp)
            entry = self.loyalty.confirm(self.user, customer.customer_id)['raffle_entry']
            self.assertEqual(entry.raffle_date.isoformat(), expected)
            self.assertEqual(entry.created_at.utcoffset(), timedelta(0))
            self.assertEqual(entry.business_timezone, 'Europe/Dublin')
        self.now = datetime.fromisoformat('2026-10-25T00:30:00+00:00'); self.confirm()
        self.now += timedelta(hours=1)
        with self.assertRaises(DuplicateVisit): self.confirm()
        self.assertEqual(len(self.entries()), 1)

    def test_same_customer_across_dublin_midnight_has_two_separate_daily_entries(self):
        self.now = datetime(2026, 10, 6, 22, 55, tzinfo=timezone.utc)
        first = self.confirm()['raffle_entry']
        self.now += timedelta(minutes=10)
        second = self.confirm()['raffle_entry']
        self.assertEqual(first.raffle_date, date(2026, 10, 6))
        self.assertEqual(second.raffle_date, date(2026, 10, 7))
        self.assertEqual(second.created_at - first.created_at, timedelta(minutes=10))
        self.assertEqual(self.entries(), [second, first])
        self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 2)

    def test_raffle_preparation_failure_rolls_back_everything(self):
        module = 'app.repository' if self.memory else 'app.loyalty_repository'
        self.seed_history(4)
        with patch(module + '.raffle_for_visit', side_effect=StorageUnavailable()):
            with self.assertRaises(StorageUnavailable): self.confirm()
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 4)
        self.assertEqual(self.repo.vouchers('tenant-a', self.customer.customer_id), [])

    def test_concurrent_attempts_one_visit_and_one_raffle(self):
        barrier = Barrier(2)
        def attempt():
            barrier.wait(timeout=5)
            try: return self.confirm()
            except DuplicateVisit: return None
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: attempt(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 1)


class MemoryRaffleTests(RaffleTests):
    memory = True


class RaffleTransactionTests(RaffleTests):
    def test_raffle_condition_failure_rolls_back_visit_counter_both_rewards(self):
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth='1990-10-07'))
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc); self.seed_history(4)
        candidate = normalize_visit(Visit(business_id='tenant-a', visit_id='blocked-random-visit',
            customer_id=self.customer.customer_id, visited_at=self.now, recorded_by=self.user.subject, visit_number=5))
        entry = raffle_for_visit(candidate)
        for key in [raffle_key(entry), raffle_date_key(entry)]:
            with self.subTest(key=key):
                self.db.items[('tenant-a', key)] = {'business_id': 'tenant-a', 'customer_id': key, 'item_type': 'TEST_COLLISION'}
                before = deepcopy(self.db.items)
                with patch('app.loyalty_service.uuid4', return_value=candidate.visit_id):
                    with self.assertRaises(ConcurrentModification): self.confirm()
                self.assertEqual(self.db.items, before); del self.db.items[('tenant-a', key)]
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 4)
        self.assertEqual(self.repo.vouchers('tenant-a', self.customer.customer_id), [])

    def test_visit_storage_failure_and_conflict_retry(self):
        self.db.injected_errors.append(ClientError({'Error': {'Code': 'AccessDeniedException'}}, 'TransactWriteItems'))
        before = deepcopy(self.db.items)
        with self.assertRaises(StorageUnavailable): self.confirm()
        self.assertEqual(self.db.items, before)
        self.db.injected_errors.append(ClientError({'Error': {'Code': 'TransactionConflictException'}}, 'TransactWriteItems'))
        result = self.confirm(); self.assertEqual(self.entries(), [result['raffle_entry']])
        with self.assertRaises(DuplicateVisit): self.confirm()
        self.assertEqual(len(self.entries()), 1)

    def test_forced_counter_race_one_transaction_commits(self):
        barrier = Barrier(2); original = self.repo._visit_state
        def state(business, customer):
            item, count = original(business, customer)
            if count == 0: barrier.wait(timeout=5)
            return item, count
        def attempt():
            try: return self.confirm()
            except DuplicateVisit: return None
        with patch.object(self.repo, '_visit_state', side_effect=state), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(len(self.repo.visits('tenant-a', self.customer.customer_id)), 1)

    def test_sdk_shapes_raffle_and_projection_in_same_two_reward_transaction(self):
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth='1990-10-07'))
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc); self.seed_history(4); self.confirm()
        writes = [params for operation, params in self.db.calls if operation == 'transact_write_items'][-1]
        types = [self.db.decode(action['Put']['Item'])['item_type'] for action in writes['TransactItems'] if 'Put' in action]
        for kind in ['RAFFLE_ENTRY', 'RAFFLE_DATE_INDEX', 'VISIT']: self.assertEqual(types.count(kind), 1)
        self.assertEqual(types.count('VOUCHER'), 2); self.assertEqual(len(writes['TransactItems']), 10)
        client = boto3.client('dynamodb', region_name='eu-west-1', aws_access_key_id='fixture', aws_secret_access_key='fixture')
        with Stubber(client) as stub:
            stub.add_response('transact_write_items', {}, writes); client.transact_write_items(**writes)


class RaffleAPITests(unittest.TestCase):
    def setUp(self):
        with patch('app.config.build_repository'), patch('app.media_storage.build_media_storage'):
            from main import create_app
        self.repo = InMemoryCustomerRepository(); self.verifier = Mock()
        self.user = UserContext('trusted-staff', None, 'tenant-a', (), Role.STAFF)
        self.verifier.verify.return_value = self.user; self.app = create_app(self.repo, self.verifier)
        self.customer = self.app.state.customer_service.create('tenant-a', data())
        self.history_path = f'/customers/{self.customer.customer_id}/raffle-entries'
        self.visit_path = f'/customers/{self.customer.customer_id}/visits'
    def call(self, method, path, body=None, token='fixture', query=''):
        return asyncio.run(request(self.app, method, path, token=token, data=body, query=query))

    def test_all_roles_history_confirm_trusted_identity(self):
        for index, role in enumerate(Role):
            self.verifier.verify.return_value = UserContext('trusted-' + role.value, None, 'tenant-a', (), role)
            self.app.state.loyalty_service.clock = lambda: datetime(2026, 10, 1 + index, 12, tzinfo=timezone.utc)
            status, result = self.call('POST', self.visit_path, {})
            self.assertEqual(status, 201)
            self.assertEqual(result['raffle_entry']['recorded_by'], 'trusted-' + role.value)
            self.assertEqual(result['raffle_entry']['visit_id'], result['visit']['visit_id'])
            status, entries = self.call('GET', self.history_path)
            self.assertEqual(status, 200); self.assertEqual(len(entries), index + 1)
            self.assertEqual(entries[0]['customer_id'], self.customer.customer_id)
        self.assertEqual(self.call('GET', self.history_path, token=None)[0], 401)

    def test_cross_business_spoofing_no_public_or_direct_creation(self):
        self.call('POST', self.visit_path, {})
        self.assertEqual(self.call('GET', self.history_path, query='business_id=tenant-b')[0], 403)
        self.verifier.verify.return_value = UserContext('other', None, 'tenant-b', (), Role.OWNER)
        self.assertEqual(self.call('GET', self.history_path)[0], 404)
        self.assertEqual(self.call('POST', self.visit_path, {})[0], 404)
        self.verifier.verify.return_value = self.user
        self.assertNotEqual(self.call('POST', self.history_path, {})[0], 201)
        self.assertEqual(self.call('GET', '/public/raffle')[0], 404)
        for key in ['business_id', 'recorded_by', 'raffle_date', 'raffle_entry']:
            self.assertEqual(self.call('POST', self.visit_path, {key: 'untrusted'})[0], 422)
        self.assertEqual(len(self.repo.raffle_entries('tenant-a', self.customer.customer_id)), 1)


    def test_manual_directory_selection_all_roles_read_only_then_same_confirm(self):
        for index, role in enumerate(Role):
            self.verifier.verify.return_value = UserContext('trusted-' + role.value, None, 'tenant-a', (), role)
            self.app.state.loyalty_service.clock = lambda: datetime(2026, 10, 1 + index, 12, tzinfo=timezone.utc)
            status, customers = self.call('GET', '/customers')
            self.assertEqual(status, 200)
            self.assertEqual([customer['customer_id'] for customer in customers], [self.customer.customer_id])
            before_visits = len(self.repo.visits('tenant-a', self.customer.customer_id))
            before_raffles = len(self.repo.raffle_entries('tenant-a', self.customer.customer_id))
            before_vouchers = len(self.repo.vouchers('tenant-a', self.customer.customer_id))
            status, selected = self.call('GET', self.visit_path)
            self.assertEqual(status, 200)
            self.assertEqual(selected['customer']['customer_id'], self.customer.customer_id)
            self.assertEqual(selected['total_visits'], index)
            self.assertEqual(len(self.repo.visits('tenant-a', self.customer.customer_id)), before_visits)
            self.assertEqual(len(self.repo.raffle_entries('tenant-a', self.customer.customer_id)), before_raffles)
            self.assertEqual(len(self.repo.vouchers('tenant-a', self.customer.customer_id)), before_vouchers)
            status, confirmed = self.call('POST', self.visit_path, {})
            self.assertEqual(status, 201)
            self.assertEqual(confirmed['visit']['recorded_by'], 'trusted-' + role.value)
            self.assertEqual(confirmed['raffle_entry']['visit_id'], confirmed['visit']['visit_id'])
            self.assertEqual(len(self.repo.visits('tenant-a', self.customer.customer_id)), before_visits + 1)
            self.assertEqual(len(self.repo.raffle_entries('tenant-a', self.customer.customer_id)), before_raffles + 1)
            self.assertEqual(self.call('POST', self.visit_path, {})[0], 409)
            self.assertEqual(len(self.repo.raffle_entries('tenant-a', self.customer.customer_id)), before_raffles + 1)

    def test_manual_selection_fifth_birthday_and_both_use_existing_rewards(self):
        self.app.state.loyalty_service.clock = lambda: datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        cases = [(4, '1990-01-01', {'LOYALTY_10'}), (0, '1990-10-07', {'BIRTHDAY_20'}),
                 (4, '1990-10-07', {'LOYALTY_10', 'BIRTHDAY_20'})]
        for index, (count, dob, expected) in enumerate(cases):
            customer = self.app.state.customer_service.create('tenant-a', data(phone=f'087123455{index}', date_of_birth=dob))
            for number in range(1, count + 1):
                visit = normalize_visit(Visit(business_id='tenant-a', visit_id=f'historical-{index}-{number}',
                    customer_id=customer.customer_id, visited_at=datetime(2026, 10, 7, 12, tzinfo=timezone.utc) - timedelta(days=count + 1 - number),
                    recorded_by='historical-recorder', visit_number=number))
                self.repo._visits[('tenant-a', visit.visit_id)] = visit
            path = f'/customers/{customer.customer_id}/visits'
            status, selected = self.call('GET', path)
            self.assertEqual(status, 200); self.assertEqual(selected['total_visits'], count)
            self.assertEqual(self.repo.raffle_entries('tenant-a', customer.customer_id), [])
            self.assertEqual(self.repo.vouchers('tenant-a', customer.customer_id), [])
            status, confirmed = self.call('POST', path, {})
            self.assertEqual(status, 201)
            self.assertEqual({voucher['type'] for voucher in confirmed['vouchers']}, expected)
            self.assertEqual(len(self.repo.raffle_entries('tenant-a', customer.customer_id)), 1)
            self.assertEqual(len(self.repo.visits('tenant-a', customer.customer_id)), count + 1)

    def test_manual_selection_is_scoped_and_inactive_confirm_rejected(self):
        other = self.app.state.customer_service.create('tenant-b', data())
        status, customers = self.call('GET', '/customers')
        self.assertEqual(status, 200)
        self.assertNotIn(other.customer_id, [customer['customer_id'] for customer in customers])
        self.assertEqual(self.call('GET', f'/customers/{other.customer_id}/visits')[0], 404)
        self.assertEqual(self.call('POST', f'/customers/{other.customer_id}/visits', {})[0], 404)
        self.app.state.customer_service.update('tenant-a', self.customer.customer_id, data(status='inactive'))
        self.assertEqual(self.call('GET', self.visit_path)[1]['customer']['status'], 'inactive')
        self.assertEqual(self.call('POST', self.visit_path, {})[0], 409)
        self.assertEqual(self.repo.raffle_entries('tenant-a', self.customer.customer_id), [])
        self.assertEqual(self.repo.visits('tenant-a', self.customer.customer_id), [])
