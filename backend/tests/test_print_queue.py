"""Durable job/snapshot/lifecycle tests; all AWS operations fake or SDK-stubbed."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4
import unittest
from unittest.mock import Mock, patch
import boto3
from botocore.exceptions import ClientError
from botocore.stub import Stubber
from app.auth import Role, UserContext
from app.print_models import PrintJobNotFound, PrintJobConflict
from app.print_service import PrintService
from app.print_repository import guard_transaction, print_key
from app.print_lifecycle import transition, LEASE_SECONDS, effective_status
from app.repository import InMemoryCustomerRepository, DuplicateVisit, StorageUnavailable
from app.tickets import jobs_for_visit
import test_raffle
from test_vouchers import data
from test_auth import request


class PrintTests(unittest.TestCase):
    memory = False
    confirm = test_raffle.RaffleTests.confirm
    seed_history = test_raffle.RaffleTests.seed_history
    def setUp(self):
        test_raffle.RaffleTests.setUp(self)
        self.owner = UserContext('manager-fixture', None, 'tenant-a', (), Role.MANAGER)
        self.printing = PrintService(self.customers, lambda: self.now)

    def jobs(self): return self.repo.print_jobs('tenant-a', self.customer.customer_id)
    def job(self): return self.jobs()[0]
    def act(self, job, action, token=None, user=None):
        return self.printing.action(user or self.owner, job.print_job_id, action, token)
    def complete(self, job):
        claim = self.act(job, 'claim'); token = claim['claim_token']
        self.act(job, 'start', token); self.act(job, 'complete', token)

    def test_normal_visit_one_job_queued_deterministic_source_no_secrets(self):
        before = self.loyalty.lookup('tenant-a', self.customer.qr_token)
        self.assertNotIn('print_jobs', before); self.assertEqual(self.jobs(), [])
        result = self.confirm()
        self.assertEqual(len(self.jobs()), 1)
        job = self.job()
        self.assertEqual(job.ticket_type, 'DAILY_RAFFLE'); self.assertEqual(job.status, 'PENDING')
        self.assertEqual(job.source_entry_id, result['raffle_entry'].raffle_entry_id)
        self.assertEqual(job.source_visit_id, result['visit'].visit_id)
        self.assertEqual(job.requested_by, self.user.subject)
        self.assertEqual(result['print_jobs'][0]['display_status'], 'Queued')
        self.assertNotIn('ticket', result['print_jobs'][0]); self.assertNotIn('claim_token', result['print_jobs'][0])
        self.assertEqual(jobs_for_visit(self.customer, result['visit'], result['raffle_entry'], [])[0].print_job_id, job.print_job_id)
        self.assertNotIn(self.customer.qr_token, job.ticket.receipt_text)
        self.assertNotIn('date_of_birth', job.ticket.model_dump())

    def test_fifth_birthday_and_combined_job_counts_source_codes(self):
        cases = [(4, '1990-01-01', {'DAILY_RAFFLE', 'LOYALTY_10'}),
                 (0, '1990-10-07', {'DAILY_RAFFLE', 'BIRTHDAY_20'}),
                 (4, '1990-10-07', {'DAILY_RAFFLE', 'LOYALTY_10', 'BIRTHDAY_20'})]
        for count, dob, types in cases:
            self.setUp()
            self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth=dob))
            self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc); self.seed_history(count)
            result = self.confirm()
            self.assertEqual({job.ticket_type for job in self.jobs()}, types)
            self.assertEqual(len(self.jobs()), len(types))
            for voucher in result['vouchers']:
                job = next(job for job in self.jobs() if job.voucher_id == voucher.voucher_id)
                self.assertEqual(job.ticket.voucher_code, voucher.voucher_code)
                self.assertEqual(job.ticket.expires_at, voucher.expires_at)
                self.assertIn(voucher.voucher_code, job.ticket.receipt_text)
                self.assertEqual(job.source_visit_id, voucher.qualifying_visit_id)

    def test_duplicate_and_concurrent_confirmations_never_duplicate_jobs(self):
        barrier = Barrier(2)
        def confirm():
            barrier.wait(timeout=5)
            try: return self.confirm()
            except DuplicateVisit: return None
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: confirm(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.jobs()), 1)
        with self.assertRaises(DuplicateVisit): self.confirm()
        self.assertEqual(len(self.jobs()), 1)

    def test_snapshot_immutable_after_customer_edit_and_reprint_preserves_original_code(self):
        self.seed_history(4); self.confirm()
        job = next(job for job in self.jobs() if job.ticket_type == 'LOYALTY_10')
        original = job.ticket.model_dump()
        self.customers.update('tenant-a', self.customer.customer_id, data(first_name='Changed', phone='0831234567'))
        self.assertEqual(self.repo.get_print_job('tenant-a', job.print_job_id).ticket.model_dump(), original)
        self.complete(job)
        visit_count = self.repo.total_visits('tenant-a', self.customer.customer_id)
        vouchers = self.repo.vouchers('tenant-a', self.customer.customer_id)
        request_id = uuid4()
        reprint = self.printing.reprint(self.owner, job.print_job_id, request_id, 'Damaged receipt verified by operator')
        self.assertEqual(reprint['status'], 'PENDING'); self.assertEqual(reprint['display_status'], 'Queued')
        self.assertEqual(reprint['ticket']['voucher_code'], job.ticket.voucher_code)
        self.assertEqual(reprint['ticket']['receipt_text'], 'REPRINT\n' + job.ticket.receipt_text)
        self.assertEqual(reprint['reprint_of'], job.print_job_id)
        again = self.printing.reprint(self.owner, job.print_job_id, request_id, 'Damaged receipt verified by operator')
        self.assertEqual(again['print_job_id'], reprint['print_job_id'])
        self.assertEqual(len(self.jobs()), 3)
        self.assertEqual(self.repo.vouchers('tenant-a', self.customer.customer_id), vouchers)
        self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), visit_count)
        self.assertEqual(len(self.repo.raffle_entries('tenant-a', self.customer.customer_id)), 1)
        self.assertEqual(self.printing.detail(self.owner, job.print_job_id)['audit'][-1]['reason'], 'Damaged receipt verified by operator')

    def test_claim_start_complete_state_machine_and_no_leaked_tokens(self):
        self.confirm(); job = self.job()
        claim = self.act(job, 'claim'); token = claim['claim_token']
        self.assertEqual(claim['attempt_count'], 1)
        with self.assertRaises(PrintJobConflict): self.act(job, 'complete', token)
        with self.assertRaises(PrintJobConflict): self.act(job, 'start', 'x' * 43)
        stranger = UserContext('other-manager', None, 'tenant-a', (), Role.MANAGER)
        with self.assertRaises(PrintJobConflict): self.act(job, 'start', token, stranger)
        self.assertEqual(self.act(job, 'start', token)['status'], 'PRINTING')
        result = self.act(job, 'complete', token)
        self.assertEqual(result['status'], 'COMPLETED'); self.assertIsNotNone(result['printed_at'])
        self.assertNotIn('claim_token', self.printing.detail(self.owner, job.print_job_id))
        self.assertNotIn('claim_token', self.printing.listing(self.owner)[0])
        with self.assertRaises(PrintJobConflict): self.act(job, 'claim')

    def test_expired_claim_safe_retry_current_token_fences_old_agent(self):
        self.confirm(); job = self.job()
        first = self.act(job, 'claim')
        self.now += timedelta(seconds=LEASE_SECONDS)
        self.assertEqual(self.printing.detail(self.owner, job.print_job_id)['status'], 'RETRYABLE')
        second = self.act(job, 'claim')
        self.assertNotEqual(first['claim_token'], second['claim_token'])
        self.assertEqual(second['attempt_count'], 2)
        with self.assertRaises(PrintJobConflict): self.act(job, 'start', first['claim_token'])
        self.assertEqual(self.act(job, 'start', second['claim_token'])['status'], 'PRINTING')

    def test_expired_printing_is_uncertain_never_automatically_reclaimed(self):
        self.confirm(); job = self.job()
        token = self.act(job, 'claim')['claim_token']; self.act(job, 'start', token)
        self.now += timedelta(seconds=LEASE_SECONDS + 1)
        self.assertEqual(self.printing.detail(self.owner, job.print_job_id)['status'], 'UNCERTAIN')
        for action, supplied in [('claim', None), ('complete', token), ('fail', token), ('start', token)]:
            with self.assertRaises(PrintJobConflict): self.act(job, action, supplied)
        self.assertEqual(len(self.jobs()), 1)
        self.assertEqual(self.act(job, 'review')['status'], 'UNCERTAIN')
        explicit = self.printing.reprint(self.owner, job.print_job_id, uuid4(), 'Printer checked; no receipt found')
        self.assertEqual(explicit['display_status'], 'Queued'); self.assertEqual(len(self.jobs()), 2)

    def test_started_failure_uncertain_and_prestart_failures_bounded_to_three(self):
        self.confirm(); job = self.job()
        for attempt in range(3):
            token = self.act(job, 'claim')['claim_token']
            result = self.act(job, 'fail', token)
            self.assertEqual(result['status'], 'RETRYABLE' if attempt < 2 else 'FAILED')
        with self.assertRaises(PrintJobConflict): self.act(job, 'claim')
        self.assertEqual(len(self.jobs()), 1)
        child = self.printing.reprint(self.owner, job.print_job_id, uuid4(), 'Operator verified safe retry after failures')
        child_job = self.repo.get_print_job('tenant-a', child['print_job_id'])
        token = self.act(child_job, 'claim')['claim_token']; self.act(child_job, 'start', token)
        self.assertEqual(self.act(child_job, 'fail', token)['status'], 'UNCERTAIN')
        with self.assertRaises(PrintJobConflict): self.act(child_job, 'claim')
        with self.assertRaises(PrintJobConflict): self.printing.reprint(self.owner, child_job.print_job_id, uuid4(), 'Attempt recursive reprint')

    def test_atomic_claim_concurrency_and_stale_repository_revision(self):
        self.confirm(); job = self.job()
        previous = self.repo.get_print_job('tenant-a', job.print_job_id)
        first = transition(previous, 'claim', self.now, self.owner.subject)
        second = transition(previous, 'claim', self.now, 'other-agent')
        barrier = Barrier(2)
        def commit(updated):
            barrier.wait(timeout=5)
            try: self.repo.save_print_change(previous, updated); return True
            except PrintJobConflict: return False
        with ThreadPoolExecutor(max_workers=2) as pool: outcomes = list(pool.map(commit, [first, second]))
        self.assertEqual(sum(outcomes), 1)
        saved = self.repo.get_print_job('tenant-a', job.print_job_id)
        self.assertEqual(saved.attempt_count, 1)
        with self.assertRaises(PrintJobConflict): self.repo.save_print_change(previous, second)

    def test_tenant_customer_visit_queries_and_internal_rows_never_customers(self):
        result = self.confirm()
        self.assertEqual(len(self.repo.print_jobs('tenant-a', self.customer.customer_id, result['visit'].visit_id)), 1)
        self.assertEqual(self.repo.print_jobs('tenant-b'), [])
        with self.assertRaises(PrintJobNotFound): self.repo.get_print_job('tenant-b', self.job().print_job_id)
        self.assertEqual(self.repo.list('tenant-a'), [self.customer])
        self.assertFalse(any(operation == 'scan' for operation, _ in self.db.calls))

    def test_ticket_layout_dublin_time_controls_and_no_historical_backfill(self):
        self.seed_history(4); self.assertEqual(self.jobs(), [])
        self.now = datetime(2026, 10, 6, 23, 5, tzinfo=timezone.utc)
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(first_name='Esc\u001b<script>', date_of_birth='1990-01-01'))
        self.confirm()
        for job in self.jobs():
            self.assertNotIn('\u001b', job.ticket.receipt_text)
            self.assertTrue(all(len(line) <= 42 for line in job.ticket.receipt_text.splitlines()))
            self.assertIn('07/10/2026 00:05 IST', job.ticket.receipt_text)
            self.assertIn('Customer signature:', job.ticket.receipt_text)
        self.assertEqual(len(self.repo.visits('tenant-a', self.customer.customer_id)), 5)

    def test_initial_trumps_branding_and_timezone_safe_ticket_sources(self):
        result = self.confirm()
        customer = self.customer.model_copy(update={'business_id': 'trumps'})
        visit = result['visit'].model_copy(update={'business_id': 'trumps'})
        entry = result['raffle_entry'].model_copy(update={'business_id': 'trumps'})
        job = jobs_for_visit(customer, visit, entry, [])[0]
        self.assertEqual(job.ticket.business_name, 'Trumps')
        self.assertTrue(job.ticket.receipt_text.startswith('Trumps\nLOYALTY BONUS'))
        self.assertIn('You have just entered our Daily Raffle!', job.ticket.receipt_text)
        self.assertIn('Please sign and place in Raffle Drum.', job.ticket.receipt_text)
        self.assertIn('GOOD LUCK!', job.ticket.receipt_text)

    def test_lookup_redemption_and_qr_regeneration_do_not_queue_tickets(self):
        from app.qr_service import QRService
        from app.voucher_service import VoucherService
        self.seed_history(4); result = self.confirm()
        before = self.jobs()
        self.loyalty.lookup('tenant-a', self.customer.qr_token)
        self.loyalty.history('tenant-a', self.customer.customer_id)
        voucher = result['vouchers'][0]
        VoucherService(self.customers, lambda: self.now).redeem(self.owner, self.customer.customer_id, voucher.voucher_id)
        qr = QRService(self.customers); qr.link('tenant-a', self.customer.customer_id)
        qr.regenerate('tenant-a', self.customer.customer_id, self.customer.qr_token)
        self.assertEqual(self.jobs(), before)

    def test_job_generation_failure_rolls_back_memory_and_dynamo(self):
        self.seed_history(4)
        module = 'app.repository' if self.memory else 'app.loyalty_repository'
        with patch(module + '.jobs_for_visit', side_effect=StorageUnavailable()):
            with self.assertRaises(StorageUnavailable): self.confirm()
        self.assertEqual(self.jobs(), []); self.assertEqual(self.repo.total_visits('tenant-a', self.customer.customer_id), 4)
        self.assertEqual(self.repo.vouchers('tenant-a', self.customer.customer_id), [])
        self.assertEqual(self.repo.raffle_entries('tenant-a', self.customer.customer_id), [])


class MemoryPrintTests(PrintTests):
    memory = True


class PrintDynamoTests(unittest.TestCase):
    setUp = PrintTests.setUp
    confirm = PrintTests.confirm
    jobs = PrintTests.jobs
    job = PrintTests.job
    seed_history = PrintTests.seed_history
    act = PrintTests.act
    memory = False

    def test_conditional_job_failure_rolls_back_all_three_tickets_and_rewards(self):
        self.customer = self.customers.update('tenant-a', self.customer.customer_id, data(date_of_birth='1990-10-07'))
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc); self.seed_history(4)
        # Fail a job put, not the visit/raffle puts. Each attempt cancels atomically.
        reasons = [{'Code': 'None'} for _ in range(13)]; reasons[-1] = {'Code': 'ConditionalCheckFailed'}
        self.db.injected_errors = [ClientError({'Error': {'Code': 'TransactionCanceledException'}, 'CancellationReasons': reasons}, 'TransactWriteItems') for _ in range(3)]
        before = deepcopy(self.db.items)
        from app.repository import ConcurrentModification
        with self.assertRaises(ConcurrentModification): self.confirm()
        self.assertEqual(self.db.items, before); self.assertEqual(self.jobs(), [])

    def test_sdk_accepts_initial_claim_start_completion_and_reprint_transactions(self):
        result = self.confirm()
        claim = self.act(self.job(), 'claim'); token = claim['claim_token']
        self.act(self.job(), 'start', token); self.act(self.job(), 'complete', token)
        self.printing.reprint(self.owner, self.job().print_job_id, uuid4(), 'Receipt damaged; explicit operator approval')
        writes = [params for operation, params in self.db.calls if operation == 'transact_write_items']
        client = boto3.client('dynamodb', region_name='eu-west-1', aws_access_key_id='fixture', aws_secret_access_key='fixture')
        with Stubber(client) as stub:
            for write in writes:
                guard_transaction(write['TransactItems']); stub.add_response('transact_write_items', {}, write)
                client.transact_write_items(**write)
        self.assertEqual(len(result['print_jobs']), 1)

    def test_transaction_action_and_size_guards_fail_before_write(self):
        with self.assertRaises(StorageUnavailable): guard_transaction([{}] * 101)
        with self.assertRaises(StorageUnavailable): guard_transaction([{'Put': {'Item': {'large': {'S': 'x' * (400 * 1024)}}}}])
        with self.assertRaises(StorageUnavailable): guard_transaction([{'Update': {}}] * 11)

    def test_customer_edit_race_rebuilds_ticket_snapshot_without_changing_rewards(self):
        original = self.db.transact_write_items; changed = False
        def write(**kwargs):
            nonlocal changed
            if not changed:
                changed = True
                self.customers.update('tenant-a', self.customer.customer_id, data(first_name='Revised'))
            return original(**kwargs)
        with patch.object(self.db, 'transact_write_items', side_effect=write): result = self.confirm()
        self.assertEqual(self.job().ticket.customer_name, 'Revised Customer')
        self.assertEqual(len(result['print_jobs']), 1)


class PrintAPITests(unittest.TestCase):
    def setUp(self):
        with patch('app.config.build_repository'), patch('app.media_storage.build_media_storage'):
            from main import create_app
        self.repo = InMemoryCustomerRepository(); self.verifier = Mock()
        self.owner = UserContext('owner-fixture', None, 'tenant-a', (), Role.OWNER)
        self.verifier.verify.return_value = self.owner
        self.app = create_app(self.repo, self.verifier)
        self.now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
        self.app.state.loyalty_service.clock = lambda: self.now
        self.app.state.print_service.clock = lambda: self.now
        self.customer = self.app.state.customer_service.create('tenant-a', data())
        self.result = self.app.state.loyalty_service.confirm(self.owner, self.customer.customer_id)
        self.job_id = self.result['print_jobs'][0]['print_job_id']
        self.path = '/print-jobs/' + self.job_id
        self.customer_path = f'/customers/{self.customer.customer_id}/print-jobs'
        self.visit_path = f'/customers/{self.customer.customer_id}/visits/{self.result["visit"].visit_id}/print-jobs'

    def call(self, method, path, data=None, token='fixture', query=''):
        return asyncio.run(request(self.app, method, path, token=token, data=data, query=query))

    def test_scoped_status_all_roles_no_ticket_claim_or_queue_administration_for_staff(self):
        for role in Role:
            self.verifier.verify.return_value = UserContext('subject-' + role.value, None, 'tenant-a', (), role)
            for path in [self.customer_path, self.visit_path]:
                status, jobs = self.call('GET', path)
                self.assertEqual(status, 200); self.assertEqual(jobs[0]['display_status'], 'Queued')
                self.assertNotIn('ticket', jobs[0]); self.assertNotIn('claim_token', jobs[0]); self.assertNotIn('audit', jobs[0])
            if role == Role.STAFF:
                for method, path, body in [('GET', '/print-jobs', None), ('GET', self.path, None),
                    ('POST', self.path + '/claim', {}), ('POST', self.path + '/review', {}),
                    ('POST', self.path + '/start', {'claim_token': 'a' * 43}),
                    ('POST', self.path + '/complete', {'claim_token': 'a' * 43}),
                    ('POST', self.path + '/fail', {'claim_token': 'a' * 43}),
                    ('POST', self.path + '/reprint', {'request_id': str(uuid4()), 'reason': 'Operator reason', 'confirmed': True})]:
                    self.assertEqual(self.call(method, path, body)[0], 403)
            else:
                self.assertEqual(self.call('GET', '/print-jobs')[0], 200)
                self.assertEqual(self.call('GET', self.path)[0], 200)
        self.assertEqual(self.call('GET', self.customer_path, token=None)[0], 401)

    def test_auth_tenant_spoofing_public_access_and_internal_records(self):
        for method, path, body in [('GET', '/print-jobs', None), ('GET', self.path, None), ('POST', self.path + '/claim', {})]:
            self.assertEqual(self.call(method, path, body, token=None)[0], 401)
            self.assertEqual(self.call(method, path, body, query='business_id=tenant-b')[0], 403)
        self.verifier.verify.return_value = UserContext('other', None, 'tenant-b', (), Role.OWNER)
        self.assertEqual(self.call('GET', '/print-jobs')[1], [])
        self.assertEqual(self.call('GET', self.customer_path)[0], 404)
        self.assertEqual(self.call('GET', self.path)[0], 404)
        self.assertEqual(self.call('POST', self.path + '/claim', {})[0], 404)
        self.assertEqual(self.call('POST', self.path + '/reprint', {'request_id': str(uuid4()), 'reason': 'Wrong tenant request', 'confirmed': True})[0], 404)
        self.assertEqual(self.call('GET', '/public/print-jobs')[0], 404)
        self.verifier.verify.return_value = self.owner
        for data in [{'business_id': 'other'}, {'claimed_by': 'spoof'}, {'status': 'COMPLETED'}, {'ticket': {}}]:
            self.assertEqual(self.call('POST', self.path + '/claim', data)[0], 422)
        self.assertEqual(len(self.call('GET', '/customers')[1]), 1)
        self.assertEqual(self.call('GET', '/customers/' + print_key(self.job_id))[0], 404)

    def test_owner_manager_can_claim_with_fences_complete_and_request_explicit_reprint(self):
        for index, role in enumerate([Role.OWNER, Role.MANAGER]):
            user = UserContext('trusted-' + role.value, None, 'tenant-a', (), role)
            self.verifier.verify.return_value = user
            customer = self.app.state.customer_service.create('tenant-a', data(phone=f'087123455{index}'))
            result = self.app.state.loyalty_service.confirm(user, customer.customer_id)
            path = '/print-jobs/' + result['print_jobs'][0]['print_job_id']
            status, claimed = self.call('POST', path + '/claim', {})
            self.assertEqual(status, 200)
            token = claimed['claim_token']; self.assertEqual(claimed['claimed_by'], user.subject)
            self.assertNotIn('claim_token', self.call('GET', path)[1])
            self.assertEqual(self.call('POST', path + '/start', {'claim_token': token})[0], 200)
            status, complete = self.call('POST', path + '/complete', {'claim_token': token})
            self.assertEqual(status, 200); self.assertEqual(complete['display_status'], 'Printed')
            body = {'request_id': str(uuid4()), 'reason': 'Operator checked damaged ticket', 'confirmed': False}
            self.assertEqual(self.call('POST', path + '/reprint', body)[0], 409)
            body['confirmed'] = True
            status, reprint = self.call('POST', path + '/reprint', body)
            self.assertEqual(status, 201); self.assertEqual(reprint['display_status'], 'Queued')
            self.assertTrue(reprint['ticket']['receipt_text'].startswith('REPRINT\n'))
            self.assertEqual(self.call('POST', path + '/reprint', body)[1]['print_job_id'], reprint['print_job_id'])
            self.assertEqual(len(self.repo.print_jobs('tenant-a', customer.customer_id)), 2)

    def test_failed_uncertain_review_queue_and_expired_tokens(self):
        claimed = self.call('POST', self.path + '/claim', {})[1]
        token = claimed['claim_token']; self.call('POST', self.path + '/start', {'claim_token': token})
        self.now += timedelta(seconds=LEASE_SECONDS)
        status, jobs = self.call('GET', '/print-jobs', query='review=true')
        self.assertEqual(status, 200); self.assertEqual(jobs[0]['status'], 'UNCERTAIN')
        self.assertEqual(self.call('POST', self.path + '/complete', {'claim_token': token})[0], 409)
        self.assertEqual(self.call('POST', self.path + '/claim', {})[0], 409)
        self.assertEqual(self.call('POST', self.path + '/review', {})[1]['status'], 'UNCERTAIN')
        self.assertEqual(len(self.repo.print_jobs('tenant-a')), 1)
