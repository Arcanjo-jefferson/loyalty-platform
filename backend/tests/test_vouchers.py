import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
from threading import Barrier
import unittest
from unittest.mock import Mock, patch
from botocore.exceptions import ClientError
import boto3
from botocore.stub import Stubber
from app.auth import Role, UserContext
from app.models import CustomerInput
from app.repository import InMemoryCustomerRepository, DuplicateVisit, InactiveCustomer, StorageUnavailable
from app.dynamodb_repository import DynamoDBCustomerRepository
from app.service import CustomerService
from app.loyalty_service import LoyaltyService
from app.voucher_service import VoucherService
from app.voucher_rules import birthday_week, midnight_utc, voucher_code
from app.voucher_repository import VoucherNotFound, VoucherNotRedeemable
from fake_dynamodb import FakeDynamoDB
from test_loyalty import data as customer_data
from test_auth import request


def data(**changes):
    return CustomerInput(**(customer_data().model_dump() | changes))


class VoucherTests(unittest.TestCase):
    memory = False
    def setUp(self):
        self.db = FakeDynamoDB(page_size=1)
        self.repo = InMemoryCustomerRepository() if self.memory else DynamoDBCustomerRepository(self.db, 'fixture-table')
        self.customers = CustomerService(self.repo)
        self.customer = self.customers.create('tenant-a', data())
        self.user = UserContext('trusted-subject', None, 'tenant-a', (), Role.STAFF)
        self.now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
        self.loyalty = LoyaltyService(self.customers, lambda: self.now)
        self.vouchers = VoucherService(self.customers, lambda: self.now)
    def visit(self): return self.loyalty.confirm(self.user, self.customer.customer_id)
    def listing(self): return self.vouchers.list('tenant-a', self.customer.customer_id)
    def fifth(self):
        for _ in range(4): self.visit(); self.now += timedelta(days=1)
        return self.visit()['vouchers'][0]
    def birthday(self):
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth='1990-10-07'))
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        return self.visit()['vouchers'][0]

    def test_first_four_fifth_tenth_and_retry(self):
        codes = []
        for count in range(1, 11):
            result = self.visit()
            self.assertEqual(result['progress'], count % 5)
            self.assertEqual(len(result['vouchers']), int(count % 5 == 0))
            if result['vouchers']:
                voucher = result['vouchers'][0]
                self.assertEqual(voucher.type, 'LOYALTY_10'); self.assertEqual(voucher.value_cents, 1000)
                self.assertEqual(voucher.qualifying_visit_id, result['visit'].visit_id)
                self.assertEqual(voucher.issued_by, self.user.subject)
                codes.append(voucher.voucher_code)
                with self.assertRaises(DuplicateVisit): self.visit()
                with self.assertRaises(DuplicateVisit): self.repo.record_visit(result['visit'])
            self.now += timedelta(days=1)
        self.assertEqual(len(set(codes)), 2); self.assertEqual(len(self.listing()), 2)
        self.assertEqual(len(self.repo.visits('tenant-a', self.customer.customer_id)), 10)

    def test_expiry_effective_lookup_and_redemption(self):
        voucher = self.fifth()
        self.assertEqual(self.vouchers.lookup('tenant-a', voucher.voucher_code).status, 'ACTIVE')
        self.now = voucher.expires_at - timedelta(microseconds=1)
        self.assertEqual(self.listing()[0].status, 'ACTIVE')
        self.now = voucher.expires_at
        self.assertEqual(self.listing()[0].status, 'EXPIRED')
        self.assertEqual(self.vouchers.lookup('tenant-a', voucher.voucher_code).status, 'EXPIRED')
        self.assertEqual(self.repo.get_voucher('tenant-a', self.customer.customer_id, voucher.voucher_id).status, 'ACTIVE')
        with self.assertRaises(VoucherNotRedeemable): self.vouchers.redeem(self.user, self.customer.customer_id, voucher.voucher_id)

    def test_midnight_expiry_and_dst(self):
        voucher = self.fifth()
        self.assertEqual(voucher.expires_at, datetime(2026, 10, 5, 23, tzinfo=timezone.utc))
        for day, hours in [(date(2026, 3, 29), 23), (date(2026, 10, 25), 25)]:
            self.assertEqual(midnight_utc(day + timedelta(days=1)) - midnight_utc(day), timedelta(hours=hours))
        self.now = datetime(2026, 10, 10, 22, 50, tzinfo=timezone.utc)
        for _ in range(4): self.visit(); self.now += timedelta(days=1)
        last = self.visit()['vouchers'][0]
        self.assertEqual(last.expires_at - last.issued_at, timedelta(minutes=10))
        self.now = last.expires_at
        self.assertEqual(self.vouchers.lookup('tenant-a', last.voucher_code).status, 'EXPIRED')

    def test_birthday_week_only_once_and_both_rewards(self):
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth='1990-10-05'))
        self.assertEqual(self.visit()['vouchers'], [])
        for _ in range(3): self.now += timedelta(days=1); self.visit()
        self.now += timedelta(days=1)
        result = self.visit()
        self.assertEqual({v.type for v in result['vouchers']}, {'LOYALTY_10', 'BIRTHDAY_20'})
        self.assertEqual(len({v.voucher_id for v in result['vouchers']}), 2)
        birthday = next(v for v in result['vouchers'] if v.type == 'BIRTHDAY_20')
        self.assertEqual(birthday.birthday_year, 2026); self.assertEqual(birthday.value_cents, 2000)
        self.assertEqual(birthday.expires_at, midnight_utc(date(2026, 10, 12)))
        self.now += timedelta(days=1)
        self.assertEqual(self.visit()['vouchers'], [])
        self.now = datetime(2027, 10, 5, 12, tzinfo=timezone.utc)
        self.assertEqual(self.visit()['vouchers'][0].birthday_year, 2027)
        self.assertEqual(len(self.listing()), 3)

    def test_birthday_sunday_expiry_and_year_boundary(self):
        voucher = self.birthday()
        self.now = datetime(2026, 10, 11, 22, 59, tzinfo=timezone.utc)
        self.assertEqual(self.vouchers.lookup('tenant-a', voucher.voucher_code).status, 'ACTIVE')
        self.now = datetime(2026, 10, 11, 23, tzinfo=timezone.utc)
        self.assertEqual(self.vouchers.lookup('tenant-a', voucher.voucher_code).status, 'EXPIRED')
        dob = date(1990, 1, 1)
        self.assertEqual(birthday_week(dob, date(2026, 12, 28)), (2027, date(2026, 12, 28), date(2027, 1, 4)))
        self.assertEqual(birthday_week(dob, date(2027, 1, 3))[0], 2027)
        self.assertIsNone(birthday_week(dob, date(2026, 12, 27)))
        self.assertIsNone(birthday_week(dob, date(2027, 1, 4)))
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth='1990-01-01'))
        self.now = datetime(2026, 12, 28, 12, tzinfo=timezone.utc)
        self.assertEqual(self.visit()['vouchers'][0].birthday_year, 2027)
        self.now = datetime(2027, 1, 1, 12, tzinfo=timezone.utc)
        self.assertFalse(any(v.type == 'BIRTHDAY_20' for v in self.visit()['vouchers']))

    def test_leap_day_rule_and_birthday_dst_week_length(self):
        dob = date(1992, 2, 29)
        self.assertIsNone(birthday_week(dob, date(2027, 2, 28)))
        self.assertEqual(birthday_week(dob, date(2027, 3, 1)), (2027, date(2027, 3, 1), date(2027, 3, 8)))
        self.assertEqual(birthday_week(dob, date(2028, 2, 29)), (2028, date(2028, 2, 28), date(2028, 3, 6)))
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth='1992-02-29'))
        self.now = datetime(2027, 2, 28, 12, tzinfo=timezone.utc)
        self.assertEqual(self.visit()['vouchers'], [])
        self.now += timedelta(days=1)
        self.assertEqual(self.visit()['vouchers'][0].birthday_year, 2027)
        for birthday, hours in [(date(1990, 3, 29), 167), (date(1990, 10, 25), 169)]:
            _, start, end = birthday_week(birthday, date(2026, birthday.month, birthday.day))
            self.assertEqual(midnight_utc(end) - midnight_utc(start), timedelta(hours=hours))

    def test_redeem_once_records_identity_and_preserves_history(self):
        voucher = self.fifth()
        saved = self.vouchers.redeem(self.user, self.customer.customer_id, voucher.voucher_id)
        self.assertEqual(saved.status, 'REDEEMED'); self.assertEqual(saved.redeemed_by, 'trusted-subject')
        self.assertEqual(saved.redeemed_at, self.now)
        with self.assertRaises(VoucherNotRedeemable): self.vouchers.redeem(self.user, self.customer.customer_id, voucher.voucher_id)
        self.assertEqual(len(self.listing()), 1)
        self.now = voucher.expires_at
        self.assertEqual(self.listing()[0].status, 'REDEEMED')

    def test_concurrent_redemption_exactly_one(self):
        voucher = self.fifth(); barrier = Barrier(2)
        def redeem(_):
            barrier.wait(timeout=5)
            try: self.vouchers.redeem(self.user, self.customer.customer_id, voucher.voucher_id); return 'success'
            except VoucherNotRedeemable: return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(redeem, range(2))), ['rejected', 'success'])

    def test_concurrent_fifth_visit_exactly_one_voucher(self):
        for _ in range(4): self.visit(); self.now += timedelta(days=1)
        barrier = Barrier(2)
        def confirm(_):
            barrier.wait(timeout=5)
            try: return self.visit()['vouchers']
            except DuplicateVisit: return []
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(confirm, range(2)))
        self.assertEqual(sum(len(v) for v in results), 1); self.assertEqual(len(self.listing()), 1)
        self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 5)

    def test_concurrent_birthday_different_dates_once_per_year(self):
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth='1990-10-07'))
        barrier = Barrier(2)
        def confirm(day):
            service = LoyaltyService(self.customers, lambda: datetime(2026, 10, day, 12, tzinfo=timezone.utc))
            barrier.wait(timeout=5)
            return service.confirm(self.user, self.customer.customer_id)
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(confirm, (6, 7)))
        self.assertEqual(sum(len(r['vouchers']) for r in results), 1); self.assertEqual(len(self.listing()), 1)
        self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 2)

    def test_lookup_normalization_tenant_scope_and_no_scan(self):
        voucher = self.fifth()
        self.assertEqual(self.vouchers.lookup('tenant-a', voucher.voucher_code.replace('-', '').lower()), voucher)
        with self.assertRaises(VoucherNotFound): self.vouchers.lookup('tenant-b', voucher.voucher_code)
        with self.assertRaises(VoucherNotFound): self.vouchers.lookup('tenant-a', 'invalid')
        outsider = UserContext('other', None, 'tenant-b', (), Role.OWNER)
        with self.assertRaises(VoucherNotFound): self.vouchers.redeem(outsider, self.customer.customer_id, voucher.voucher_id)
        self.assertEqual(self.repo.vouchers('tenant-b', self.customer.customer_id), [])
        self.assertFalse(any(operation == 'scan' for operation, _ in self.db.calls))
        self.assertEqual(self.repo.list('tenant-a'), [self.customer])

    def test_lookup_inactive_and_daily_duplicate_issue_nothing(self):
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth='1990-10-01'))
        self.loyalty.lookup('tenant-a', self.customer.qr_token); self.assertEqual(self.listing(), [])
        self.visit()
        with self.assertRaises(DuplicateVisit): self.visit()
        self.assertEqual(len(self.listing()), 1)
        self.now += timedelta(days=1)
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(status='inactive'))
        with self.assertRaises(InactiveCustomer): self.visit()
        self.assertEqual(len(self.listing()), 1)

    def test_voucher_visit_and_customer_updates_preserve_private_media_and_qr(self):
        original_qr = self.customer.qr_token
        self.repo.save_media('tenant-a', self.customer.customer_id, 'profile', {'revision': 'fixture', 'key': 'private-reference'}, expected_revision=None)
        self.fifth()
        updated = self.customers.update('tenant-a', self.customer.customer_id, data(phone='0851234567'))
        self.assertEqual(self.repo.get_media('tenant-a', self.customer.customer_id, 'profile')['key'], 'private-reference')
        self.assertEqual(updated.qr_token, original_qr)
        self.assertEqual(self.loyalty.lookup('tenant-a', original_qr)['total_visits'], 5)
        self.assertEqual(len(self.listing()), 1)
        self.assertEqual(self.repo.list('tenant-a'), [updated])

    def test_secure_codes_and_atomic_collision_recovery(self):
        self.assertEqual(len({voucher_code() for _ in range(100)}), 100)
        voucher = self.fifth(); self.now += timedelta(days=1)
        for _ in range(4): self.visit(); self.now += timedelta(days=1)
        replacement = voucher_code()
        with patch('app.voucher_rules.voucher_code', side_effect=[voucher.voucher_code, replacement]): result = self.visit()
        self.assertEqual(result['vouchers'][0].voucher_code, replacement)
        self.assertEqual(len(self.listing()), 2); self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 10)


class MemoryVoucherTests(VoucherTests):
    memory = True


class DynamoVoucherFailureTests(VoucherTests):
    def test_forced_concurrent_reward_transactions_only_one_commits(self):
        for _ in range(4): self.visit(); self.now += timedelta(days=1)
        barrier = Barrier(2); original = self.repo.visits
        def history(*args):
            result = original(*args)
            if len(result) == 4: barrier.wait(timeout=5)
            return result
        def confirm(_):
            try: self.visit(); return 'success'
            except DuplicateVisit: return 'duplicate'
        with patch.object(self.repo, 'visits', side_effect=history), ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(confirm, range(2))), ['duplicate', 'success'])
        self.assertEqual(len(self.listing()), 1)
        self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 5)

    def test_forced_concurrent_redemption_condition_rejects_second(self):
        voucher = self.fifth(); barrier = Barrier(2); original = self.repo.get_voucher
        def read(*args):
            result = original(*args)
            if result.status == 'ACTIVE': barrier.wait(timeout=5)
            return result
        def redeem(_):
            try: self.vouchers.redeem(self.user, self.customer.customer_id, voucher.voucher_id); return 'success'
            except VoucherNotRedeemable: return 'rejected'
        with patch.object(self.repo, 'get_voucher', side_effect=read), ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(redeem, range(2))), ['rejected', 'success'])

    def test_two_rewards_colliding_codes_regenerate_before_transaction(self):
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth='1990-10-05'))
        for _ in range(4): self.visit(); self.now += timedelta(days=1)
        same = voucher_code(); unique = [voucher_code(), voucher_code()]
        with patch('app.voucher_rules.voucher_code', side_effect=[same, same, *unique]): result = self.visit()
        self.assertEqual({v.voucher_code for v in result['vouchers']}, set(unique))
        self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 5)

    def test_reward_transaction_failure_rolls_back_entire_visit(self):
        for _ in range(4): self.visit(); self.now += timedelta(days=1)
        before = deepcopy(self.db.items)
        self.db.injected_errors.append(ClientError({'Error': {'Code': 'AccessDeniedException'}}, 'TransactWriteItems'))
        with self.assertRaises(StorageUnavailable): self.visit()
        self.assertEqual(self.db.items, before); self.assertEqual(self.listing(), [])
        self.assertEqual(len(self.visit()['vouchers']), 1)

    def test_customer_dob_edit_race_rechecks_birthday(self):
        original = self.db.transact_write_items; changed = False
        def transaction(**kwargs):
            nonlocal changed
            if not changed:
                changed = True
                item = self.db.items[('tenant-a', self.customer.customer_id)]
                item['date_of_birth'] = '1990-10-01'; item['updated_at'] = '2026-10-01T12:00:00Z'
            return original(**kwargs)
        with patch.object(self.db, 'transact_write_items', side_effect=transaction): result = self.visit()
        self.assertEqual(result['vouchers'][0].type, 'BIRTHDAY_20')

    def test_real_sdk_accepts_reward_and_redemption_transactions(self):
        voucher = self.fifth()
        writes = [params for operation, params in self.db.calls if operation == 'transact_write_items']
        client = boto3.client('dynamodb', region_name='eu-west-1', aws_access_key_id='fixture', aws_secret_access_key='fixture')
        with Stubber(client) as stub:
            stub.add_response('transact_write_items', {}, writes[-1]); client.transact_write_items(**writes[-1])
            self.vouchers.redeem(self.user, self.customer.customer_id, voucher.voucher_id)
            write = [params for operation, params in self.db.calls if operation == 'transact_write_items'][-1]
            stub.add_response('transact_write_items', {}, write); client.transact_write_items(**write)
            stub.assert_no_pending_responses()


class VoucherAPITests(unittest.TestCase):
    def setUp(self):
        with patch('app.config.build_repository'), patch('app.media_storage.build_media_storage'):
            from main import create_app
        self.repo = InMemoryCustomerRepository(); self.verifier = Mock()
        self.user = UserContext('trusted-cognito-subject', None, 'tenant-a', (), Role.STAFF)
        self.verifier.verify.return_value = self.user
        self.app = create_app(self.repo, self.verifier)
        self.customer = self.app.state.customer_service.create('tenant-a', data(date_of_birth='1990-10-07'))
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        self.app.state.loyalty_service.clock = lambda: self.now
        self.app.state.voucher_service.clock = lambda: self.now
        self.voucher = self.app.state.loyalty_service.confirm(self.user, self.customer.customer_id)['vouchers'][0]
        self.list_path = f'/customers/{self.customer.customer_id}/vouchers'
        self.redeem_path = f'{self.list_path}/{self.voucher.voucher_id}/redeem'
    def call(self, method, path, data=None, token='fixture', query=''):
        return asyncio.run(request(self.app, method, path, token=token, data=data, query=query))

    def test_authentication_roles_identity_and_spoofing(self):
        for path, method, body in [(self.list_path, 'GET', None), ('/vouchers/lookup', 'POST', {'voucher_code': self.voucher.voucher_code}), (self.redeem_path, 'POST', {})]:
            self.assertEqual(self.call(method, path, body, token=None)[0], 401)
            for role in Role:
                self.verifier.verify.return_value = UserContext('trusted-' + role.value, None, 'tenant-a', (), role)
                if method == 'GET' or path.endswith('lookup'): self.assertEqual(self.call(method, path, body)[0], 200)
        for body in [{'redeemed_by': 'attacker'}, {'business_id': 'tenant-b'}, {'issued_by': 'attacker'}]:
            self.assertEqual(self.call('POST', self.redeem_path, body)[0], 422)
        code, result = self.call('POST', self.redeem_path, {})
        self.assertEqual(code, 200); self.assertEqual(result['redeemed_by'], 'trusted-STAFF')
        self.assertEqual(self.call('POST', self.redeem_path, {})[0], 409)

    def test_each_role_can_redeem(self):
        for index, role in enumerate(Role):
            self.verifier.verify.return_value = UserContext('subject-' + role.value, None, 'tenant-a', (), role)
            customer = self.app.state.customer_service.create('tenant-a', data(phone=f'087123456{index}', date_of_birth='1990-10-07'))
            voucher = self.app.state.loyalty_service.confirm(self.verifier.verify.return_value, customer.customer_id)['vouchers'][0]
            path = f'/customers/{customer.customer_id}/vouchers/{voucher.voucher_id}/redeem'
            code, result = self.call('POST', path, {})
            self.assertEqual(code, 200)
            self.assertEqual(result['redeemed_by'], 'subject-' + role.value)

    def test_cross_tenant_and_effective_expiry(self):
        self.assertEqual(self.call('GET', self.list_path, query='business_id=tenant-b')[0], 403)
        self.verifier.verify.return_value = UserContext('other', None, 'tenant-b', (), Role.OWNER)
        self.assertEqual(self.call('GET', self.list_path)[0], 404)
        self.assertEqual(self.call('POST', '/vouchers/lookup', {'voucher_code': self.voucher.voucher_code})[0], 404)
        self.assertEqual(self.call('POST', self.redeem_path, {})[0], 404)
        self.verifier.verify.return_value = self.user; self.now = self.voucher.expires_at
        self.assertEqual(self.call('GET', self.list_path)[1][0]['status'], 'EXPIRED')
        self.assertEqual(self.call('POST', self.redeem_path, {})[0], 409)
        self.assertEqual(self.call('POST', '/vouchers/lookup', {'voucher_code': self.voucher.voucher_code, 'business_id': 'tenant-b'})[0], 422)
        self.assertEqual(self.call('POST', self.list_path, {})[0], 422)  # Media catch-all rejects this non-category.
        self.assertEqual(len(self.repo.vouchers('tenant-a', self.customer.customer_id)), 1)
