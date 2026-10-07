from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from app.dynamodb_repository import DynamoDBCustomerRepository
from app.service import CustomerService
from app.loyalty_service import LoyaltyService
from app.auth import UserContext, Role
from scripts.seed_acceptance_visits import seed, verify
from fake_dynamodb import FakeDynamoDB
from test_loyalty import data


class AcceptanceSeedTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDynamoDB(page_size=1)
        self.repo = DynamoDBCustomerRepository(self.db, 'fixture-table')
        self.customers = CustomerService(self.repo)
        self.customer = self.customers.create('fixture-business', data())
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    def seed(self, apply=False): return seed(self.repo, 'fixture-business', self.customer.customer_id, apply=apply, now=self.now)

    def test_dry_run_printable_plan_has_no_writes(self):
        before = deepcopy(self.db.items); calls = len(self.db.calls)
        plan = self.seed()
        self.assertEqual(self.db.items, before)
        self.assertFalse(any(op == 'transact_write_items' for op, _ in self.db.calls[calls:]))
        self.assertEqual(len(plan['visit_records']), 4)
        self.assertEqual(plan['customer_counter_change']['loyalty_total_visits'], {'before': 0, 'after': 4})

    def test_apply_four_dates_progress_and_normal_fifth_issues_voucher(self):
        self.seed(True)
        check = verify(self.repo, 'fixture-business', self.customer.customer_id, now=self.now)
        self.assertEqual((check['total_visits'], check['progress'], check['visits_until_reward']), (4, 4, 1))
        self.assertEqual([v['local_visit_date'] for v in check['visits']], ['2026-10-03', '2026-10-04', '2026-10-05', '2026-10-06'])
        self.assertEqual(self.repo.vouchers('fixture-business', self.customer.customer_id), [])
        self.assertFalse(any(item['item_type'] in ['VOUCHER', 'REWARD_LOCK', 'VOUCHER_CODE'] for item in self.db.items.values()))
        result = LoyaltyService(self.customers, lambda: self.now).confirm(UserContext('fixture-sub', None, 'fixture-business', (), Role.STAFF), self.customer.customer_id)
        self.assertEqual(result['total_visits'], 5)
        self.assertEqual(result['vouchers'][0].type, 'LOYALTY_10')

    def test_existing_visits_and_rerun_refused_without_changes(self):
        self.seed(True); before = deepcopy(self.db.items)
        for apply in (False, True):
            with self.assertRaises(ValueError): self.seed(apply)
        self.assertEqual(self.db.items, before)
        self.assertEqual(len(self.repo.visits('fixture-business', self.customer.customer_id)), 4)

    def test_missing_inactive_wrong_business_refused(self):
        for business, customer in [('other-business', self.customer.customer_id), ('fixture-business', 'missing')]:
            with self.assertRaises(ValueError): seed(self.repo, business, customer, apply=True, now=self.now)
        self.customers.update('fixture-business', self.customer.customer_id, data(status='inactive'))
        with self.assertRaises(ValueError): self.seed(True)

    def test_reward_lock_or_voucher_refused(self):
        key = ('fixture-business', 'REWARD#' + self.customer.customer_id + '#BIRTHDAY_20#2026')
        self.db.items[key] = {'business_id': key[0], 'customer_id': key[1], 'item_type': 'REWARD_LOCK'}
        with self.assertRaises(ValueError): self.seed(True)
        del self.db.items[key]
        with patch.object(self.repo, 'vouchers', return_value=[object()]):
            with self.assertRaises(ValueError): self.seed(True)

    def test_zero_counter_with_orphan_history_refused(self):
        self.seed(True)
        self.db.items[('fixture-business', self.customer.customer_id)]['loyalty_total_visits'] = 0
        with self.assertRaises(ValueError): self.seed(True)

    def test_concurrent_runs_only_one_atomic_seed(self):
        def run(_):
            try: self.seed(True); return 'seeded'
            except ValueError: return 'refused'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(run, range(2))), ['refused', 'seeded'])
        self.assertEqual(self.repo.total_visits('fixture-business', self.customer.customer_id), 4)

    def test_customer_change_race_rolls_back_all_visits(self):
        original = self.db.transact_write_items
        def write(**params):
            self.db.items[('fixture-business', self.customer.customer_id)]['status'] = 'inactive'
            return original(**params)
        with patch.object(self.db, 'transact_write_items', side_effect=write), self.assertRaises(ValueError): self.seed(True)
        self.assertEqual(self.repo.visits('fixture-business', self.customer.customer_id), [])
        self.assertEqual(self.repo.total_visits('fixture-business', self.customer.customer_id), 0)

    def test_dst_history_and_media_preserved(self):
        self.now = datetime(2026, 3, 31, 12, tzinfo=timezone.utc)
        self.repo.save_media('fixture-business', self.customer.customer_id, 'profile', {'revision': 'fixture', 'key': 'private-reference'}, expected_revision=None)
        self.seed(True)
        visits = self.repo.visits('fixture-business', self.customer.customer_id)
        self.assertEqual(visits[0].visited_at.hour, 12)
        self.assertEqual(visits[-1].visited_at.hour, 11)
        self.assertEqual(self.repo.get_media('fixture-business', self.customer.customer_id, 'profile')['key'], 'private-reference')
        self.assertEqual(self.repo.get('fixture-business', self.customer.customer_id).qr_token, self.customer.qr_token)
