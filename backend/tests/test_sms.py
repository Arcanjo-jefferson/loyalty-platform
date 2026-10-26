"""Offline SMS contracts, fake DynamoDB parity and human API permissions."""
import asyncio
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from dataclasses import replace
from unittest.mock import Mock, patch
from uuid import uuid4
from fastapi import HTTPException
from app.auth import Role, UserContext
from app.models import CustomerInput
from app.repository import InMemoryCustomerRepository, StorageUnavailable
from app.dynamodb_repository import DynamoDBCustomerRepository
from app.service import CustomerService
from app.sms_models import Compose, SMSSettings, estimate
from app.sms_provider import SafeRetry, SimulatedSMSProvider
from app.sms_service import SMSService, suppression_key
from app.sms_repository import SMSConflict
from fake_dynamodb import FakeDynamoDB
from test_auth import request

class SMSMemoryTests(unittest.TestCase):
    dynamo = False
    def setUp(self):
        self.db = FakeDynamoDB(page_size=2)
        self.repo = DynamoDBCustomerRepository(self.db, 'fixture-table') if self.dynamo else InMemoryCustomerRepository()
        self.customers = CustomerService(self.repo)
        self.a = self.create('Sarah', '0831234567'); self.b = self.create('Jane', '0871234567')
        self.other = self.create('Other', '0831234567', 'other-business')
        self.user = UserContext('trusted-owner', None, 'trumps', (), Role.OWNER)
        self.now = datetime.now(timezone.utc) + timedelta(seconds=1)
        self.settings = SMSSettings(); self.provider = Mock(wraps=SimulatedSMSProvider())
        self.service = SMSService(self.customers, provider=self.provider, clock=lambda: self.now, settings=lambda b: self.settings)
    def create(self, name, phone, business='trumps'):
        return self.customers.create(business, CustomerInput(first_name=name, last_name='Fictional', phone=phone, date_of_birth='1990-01-01', marketing_consent=True))
    def data(self, bulk=False): return Compose(audience='all' if bulk else 'individual', customer_id=None if bulk else self.a.customer_id, message='Hi {first_name}! Reply STOP to opt out.')
    def queue(self, bulk=False):
        preview = self.service.preview(self.user, self.data(bulk))
        return self.service.confirm(self.user, preview['campaign_id'], True)
    def edit(self, customer, **changes):
        values = {key: getattr(customer, key) for key in CustomerInput.model_fields}
        return self.customers.update(customer.business_id, customer.customer_id, CustomerInput(**(values | changes)))
    def test_preview_is_not_delivery_or_budget_reservation(self):
        preview = self.service.preview(self.user, self.data())
        self.assertEqual(preview['recipient_count'], 1); self.assertEqual(preview['recipients'][0]['body'], 'Hi Sarah! Reply STOP to opt out.')
        self.assertNotIn('Jane', str(preview)); self.assertEqual(preview['created_by'], self.user.subject)
        self.assertEqual(self.service.history('trumps'), []); self.assertEqual(self.service.summary('trumps')['reserved_micros'], 0)
        self.provider.send.assert_not_called()
    def test_bulk_confirmation_simulation_history_and_repeat_process(self):
        result = self.queue(True)
        self.assertEqual((result['recipient_count'], result['total_segments'], result['estimated_cost_micros']), (2, 2, 200000))
        self.assertEqual(self.service.process('trumps')['processed'], 2)
        self.service.process('trumps'); self.assertEqual(self.provider.send.call_count, 2)
        history = self.service.history('trumps')[0]
        self.assertEqual(history['status'], 'FINISHED')
        self.assertEqual({r['body'].split('!')[0] for r in history['recipients']}, {'Hi Sarah', 'Hi Jane'})
        self.assertTrue(all(r['status'] == 'SIMULATED' and r['consent_timestamp'] and r['updated_at'] and r['consent_decision'] == 'EXPLICIT_OPT_IN_RECHECKED' for r in history['recipients']))
    def test_inactive_missing_consent_suppressed_invalid_excluded(self):
        self.edit(self.a, marketing_consent=False); self.edit(self.b, status='inactive')
        draft = self.service.preview(self.user, self.data(True)); self.assertEqual(draft['recipient_count'], 0)
        with self.assertRaises(HTTPException): self.service.confirm(self.user, draft['campaign_id'], True)
        self.edit(self.a, marketing_consent=True); self.service.suppress(self.user, self.a.customer_id)
        self.edit(self.a, first_name='Changed')
        self.assertEqual(self.service.preview(self.user, self.data())['recipient_count'], 0)
        self.assertFalse(self.service.eligible(self.a.model_copy(update={'phone': 'invalid'})))
    def test_confirmation_eligibility_recheck_creates_no_partial_queue(self):
        draft = self.service.preview(self.user, self.data()); self.edit(self.a, marketing_consent=False)
        with self.assertRaises(HTTPException): self.service.confirm(self.user, draft['campaign_id'], True)
        self.assertEqual(self.service.summary('trumps')['reserved_micros'], 0); self.assertEqual(self.service.history('trumps'), [])
    def test_dispatch_rechecks_phone_and_consent(self):
        self.queue(); self.edit(self.a, phone='0891234567'); self.service.process('trumps')
        self.provider.send.assert_not_called(); self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'SUPPRESSED')
    def test_dispatch_withdrawal_and_atomic_customer_fence(self):
        campaign = self.queue(); old = self.service.get('trumps', campaign['campaign_id']); self.edit(self.a, marketing_consent=False)
        with self.assertRaises(SMSConflict): self.service.store.commit('trumps', [(old, old)], customer=self.a)
        self.service.process('trumps'); self.provider.send.assert_not_called()
    def test_optout_after_queue_and_atomic_suppression_fence(self):
        campaign = self.queue(); old = self.service.get('trumps', campaign['campaign_id']); self.service.suppress(self.user, self.a.customer_id)
        with self.assertRaises(SMSConflict): self.service.store.commit('trumps', [(old, old)], customer=self.a, absent=suppression_key(self.a.phone))
        self.service.process('trumps'); self.provider.send.assert_not_called()
    def test_budget_cap_and_confirmation_idempotency(self):
        self.settings = replace(self.settings, monthly_limit_micros=100000)
        queued = self.queue()
        for _ in range(2): self.service.confirm(self.user, queued['campaign_id'], True)
        self.assertEqual(self.service.summary('trumps')['reserved_micros'], 100000)
        with self.assertRaises(HTTPException): self.queue()
        self.assertEqual(len(self.service.history('trumps')), 1)
    def test_concurrent_campaign_budget_reservation_and_dispatch(self):
        self.settings = replace(self.settings, monthly_limit_micros=100000)
        drafts = [self.service.preview(self.user, self.data()) for _ in range(2)]
        def confirm(d):
            try: self.service.confirm(self.user, d['campaign_id'], True); return True
            except HTTPException: return False
        with ThreadPoolExecutor(max_workers=2) as pool: self.assertEqual(sum(pool.map(confirm, drafts)), 1)
        with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(lambda _: self.service.process('trumps'), range(2)))
        self.assertEqual(self.provider.send.call_count, 1)
    def test_concurrent_identical_confirmation_reserves_once(self):
        d = self.service.preview(self.user, self.data())
        with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: self.service.confirm(self.user, d['campaign_id'], True), range(4)))
        self.assertEqual({r['campaign_id'] for r in results}, {d['campaign_id']}); self.assertEqual(self.service.summary('trumps')['reserved_micros'], 100000)
    def test_uncertain_provider_is_not_retried_or_logged(self):
        self.queue(); self.provider.send.side_effect = TimeoutError('secret content')
        self.service.process('trumps'); self.service.process('trumps')
        history = self.service.history('trumps'); self.assertEqual(history[0]['recipients'][0]['status'], 'UNKNOWN')
        self.assertNotIn('secret content', str(history)); self.assertEqual(self.provider.send.call_count, 1)
    def test_safe_retries_have_backoff_and_limit(self):
        self.queue(); self.provider.send.side_effect = SafeRetry()
        self.service.process('trumps'); self.service.process('trumps'); self.assertEqual(self.provider.send.call_count, 1)
        for _ in range(4): self.now += timedelta(seconds=31); self.service.process('trumps')
        self.assertEqual(self.provider.send.call_count, 3); self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'FAILED')
    def test_abandoned_submission_never_replays(self):
        c = self.queue(); old = self.service.get('trumps', c['campaign_id']); changed = deepcopy(old)
        changed['recipients'][0].update(status='SUBMITTING', lease_until=(self.now - timedelta(seconds=1)).isoformat())
        self.service.store.commit('trumps', [(old, changed)]); self.service.process('trumps')
        self.provider.send.assert_not_called(); self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'UNKNOWN')
    def test_expired_preview_unconfirmed_and_config_change(self):
        d = self.service.preview(self.user, self.data())
        with self.assertRaises(HTTPException): self.service.confirm(self.user, d['campaign_id'], False)
        self.settings = replace(self.settings, segment_price_micros=200000)
        with self.assertRaises(HTTPException): self.service.confirm(self.user, d['campaign_id'], True)
        self.now += timedelta(minutes=16)
        with self.assertRaises(HTTPException): self.service.confirm(self.user, d['campaign_id'], True)
    def test_tenant_scope_internal_rows_and_persistence_between_services(self):
        c = self.queue(); self.service.suppress(self.user, self.b.customer_id)
        self.assertEqual(len(self.repo.list('trumps')), 2); self.assertEqual(self.service.history('other-business'), [])
        self.assertEqual(self.service.process('other-business')['processed'], 0)
        with self.assertRaises(HTTPException): self.service.get('other-business', c['campaign_id'])
        from app.service import CustomerNotFound
        with self.assertRaises(CustomerNotFound): self.service.preview(self.user, Compose(audience='individual', customer_id=self.other.customer_id, message='Hi'))
        self.assertEqual(len(SMSService(self.customers).history('trumps')), 1)
        if self.dynamo:
            self.assertIsNone(self.repo.get('trumps', 'SMS_CAMPAIGN#' + c['campaign_id']))
            self.assertTrue(all(name in {'query', 'get_item', 'transact_write_items'} for name, _ in self.db.calls))
    def test_settings_dublin_month_and_twilio_forbidden(self):
        self.now = datetime(2026, 6, 30, 23, 30, tzinfo=timezone.utc)
        self.assertEqual(self.service.summary('trumps')['budget_month'], '2026-07')
        self.assertEqual(SMSSettings(provider='twilio').provider, 'twilio')
        with self.assertRaises(ValueError): SMSSettings(provider='unknown')
        with patch.dict('os.environ', {'SMS_BUSINESS_SETTINGS_JSON': '{"trumps":{"monthly_limit_micros":42,"sender":"Trumps test"}}'}):
            self.assertEqual(SMSSettings.for_business('trumps').monthly_limit_micros, 42)
            self.assertNotEqual(SMSSettings.for_business('other-business').sender, 'Trumps test')

class SMSDynamoTests(SMSMemoryTests):
    dynamo = True
    def test_storage_failure_rolls_back_budget(self):
        from botocore.exceptions import ClientError
        d = self.service.preview(self.user, self.data())
        self.db.injected_errors.append(ClientError({'Error': {'Code': 'InternalServerError'}}, 'TransactWriteItems'))
        with self.assertRaises(StorageUnavailable): self.service.confirm(self.user, d['campaign_id'], True)
        self.assertEqual(self.service.summary('trumps')['reserved_micros'], 0)
        self.assertEqual(self.service.get('trumps', d['campaign_id'])['status'], 'DRAFT')

class SMSEstimateTests(unittest.TestCase):
    def test_encoding_boundaries(self):
        for n, count in [(160, 1), (161, 2), (306, 2), (307, 3)]: self.assertEqual(estimate('a' * n)['segments'], count)
        self.assertEqual(estimate('€' * 80)['segments'], 1); self.assertEqual(estimate('€' * 81)['segments'], 2)
        self.assertEqual(estimate('漢' * 70)['segments'], 1); self.assertEqual(estimate('漢' * 71)['segments'], 2)
        self.assertEqual(estimate('😀' * 36)['segments'], 2); self.assertEqual(estimate('😀')['units'], 2)
        for message in ['{customer.phone}', '{other_name}', '']:
            with self.assertRaises(ValueError): Compose(audience='all', message=message)

class SMSAPITests(unittest.TestCase):
    def setUp(self):
        with patch('app.config.build_repository'), patch('app.media_storage.build_media_storage'):
            from main import create_app
        self.repo = InMemoryCustomerRepository(); self.verifier = Mock(); self.user = UserContext('verified-owner', None, 'trumps', (), Role.OWNER)
        self.verifier.verify.return_value = self.user; self.app = create_app(self.repo, self.verifier)
        self.customer = self.app.state.customer_service.create('trumps', CustomerInput(first_name='Sarah', last_name='Fictional', phone='0831234567', date_of_birth='1990-01-01', marketing_consent=True))
    def call(self, method, path, data=None, token='fixture', query=''):
        return asyncio.run(request(self.app, method, path, token=token, data=data, query=query))
    def test_owner_manager_workflow(self):
        for role in [Role.OWNER, Role.MANAGER]:
            self.verifier.verify.return_value = replace(self.user, role=role)
            status, draft = self.call('POST', '/sms/preview', {'audience': 'all', 'message': 'Hi {first_name}'})
            self.assertEqual(status, 200)
            self.assertEqual(self.call('POST', '/sms/campaigns/' + draft['campaign_id'] + '/confirm', {'confirmed': True})[0], 200)
            self.assertEqual(self.call('POST', '/sms/simulate', {})[0], 200); self.assertEqual(self.call('GET', '/sms/history')[0], 200)
    def test_staff_denied_anonymous_unauthorized(self):
        self.verifier.verify.return_value = replace(self.user, role=Role.STAFF)
        for method, path, data in [('GET', '/sms/settings', None), ('GET', '/sms/history', None), ('POST', '/sms/preview', {'audience': 'all', 'message': 'Hi'}), ('POST', '/sms/simulate', {}), ('POST', f'/sms/customers/{self.customer.customer_id}/suppress', {'confirmed': True}), ('POST', f'/sms/campaigns/{uuid4()}/confirm', {'confirmed': True})]:
            self.assertEqual(self.call(method, path, data)[0], 403); self.assertEqual(self.call(method, path, data, token=None)[0], 401)
    def test_tenant_and_estimate_spoofing(self):
        self.assertEqual(self.call('GET', '/sms/history', query='business_id=other-business')[0], 403)
        self.assertEqual(self.call('POST', '/sms/preview', {'audience': 'all', 'message': 'Hi', 'business_id': 'other-business'})[0], 422)
        _, d = self.call('POST', '/sms/preview', {'audience': 'all', 'message': 'Hi'})
        path = '/sms/campaigns/' + d['campaign_id'] + '/confirm'
        self.assertEqual(self.call('POST', path, {'confirmed': True, 'estimated_cost_micros': 0})[0], 422)
        self.verifier.verify.return_value = replace(self.user, subject='other-manager')
        self.assertEqual(self.call('POST', path, {'confirmed': True})[0], 403)
        self.verifier.verify.return_value = replace(self.user, business_id='other-business')
        self.assertEqual(self.call('POST', path, {'confirmed': True})[0], 404); self.assertEqual(self.call('GET', '/sms/history')[1], [])


class SMSAdditionalTests(unittest.TestCase):
    dynamo = False
    setUp = SMSMemoryTests.setUp
    create = SMSMemoryTests.create
    data = SMSMemoryTests.data
    queue = SMSMemoryTests.queue
    def test_budget_rollover_cancels_old_month_queued_output(self):
        self.now = datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc)
        self.queue(); self.now += timedelta(minutes=2)
        self.service.process('trumps'); self.provider.send.assert_not_called()
        self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['reason'], 'BUDGET_MONTH_CLOSED')
    def test_bulk_200_recipients_single_atomic_outbox_and_per_recipient_results(self):
        customers = [self.a.model_copy(update={'customer_id': str(uuid4()), 'phone': '+35383' + f'{i:07d}'}) for i in range(200)]
        with patch.object(self.customers, 'list', return_value=customers):
            draft = self.service.preview(self.user, self.data(True))
            self.assertEqual(draft['recipient_count'], 200)
            queued = self.service.confirm(self.user, draft['campaign_id'], True)
            self.assertEqual(queued['estimated_cost_micros'], 20000000)
        self.assertEqual(len(self.service.get('trumps', draft['campaign_id'])['recipients']), 200)
    def test_over_limit_customer_count_rejected_without_partial_outbox(self):
        customers = [self.a.model_copy(update={'customer_id': str(uuid4()), 'phone': '+35383' + f'{i:07d}'}) for i in range(201)]
        with patch.object(self.customers, 'list', return_value=customers):
            with self.assertRaises(HTTPException): self.service.preview(self.user, self.data(True))
        self.assertEqual(self.service.history('trumps'), [])


class SMSAdditionalDynamoTests(SMSAdditionalTests):
    dynamo = True


class SMSSearchMemoryTests(unittest.TestCase):
    dynamo = False
    setUp = SMSMemoryTests.setUp
    create = SMSMemoryTests.create
    edit = SMSMemoryTests.edit
    def test_partial_first_last_full_names_and_equivalent_irish_phones(self):
        for query in ['sAr', 'Sarah Fic', '0831234567', '831234567', '+353831234567', '353831234567', '083', '83123']:
            result = self.service.search_customers('trumps', query)
            self.assertEqual(result['total_matches'], 1, query)
            customer = result['results'][0]
            self.assertEqual(customer['customer_id'], self.a.customer_id)
            self.assertTrue(customer['sms_eligible'])
            self.assertNotIn(self.a.phone, str(customer))
            self.assertTrue(customer['masked_phone'].endswith('4567'))
            self.assertEqual(set(customer), {'customer_id', 'name', 'first_name', 'masked_phone', 'sms_eligible', 'ineligible_reason'})
        self.assertEqual(self.service.search_customers('trumps', 'fiction')['total_matches'], 2)
        self.assertEqual(self.service.search_customers('trumps', '   ')['results'], [])
        self.assertEqual(self.service.search_customers('trumps', 'unknown')['results'], [])
    def test_ineligible_matches_are_visible_with_reasons_and_cannot_queue(self):
        self.edit(self.a, marketing_consent=False)
        row = self.service.search_customers('trumps', 'Sarah')['results'][0]
        self.assertFalse(row['sms_eligible']); self.assertIn('consent', row['ineligible_reason'])
        self.edit(self.a, marketing_consent=True, status='inactive')
        self.assertIn('inactive', self.service.search_customers('trumps', 'Sarah')['results'][0]['ineligible_reason'])
        self.edit(self.a, marketing_consent=True)
        self.service.suppress(self.user, self.a.customer_id)
        self.assertIn('opted out', self.service.search_customers('trumps', 'Sarah')['results'][0]['ineligible_reason'])
        draft = self.service.preview(self.user, Compose(audience='individual', customer_id=self.a.customer_id, message='Hi'))
        self.assertEqual(draft['recipient_count'], 0)
        with self.assertRaises(HTTPException): self.service.confirm(self.user, draft['campaign_id'], True)
        self.provider.send.assert_not_called()
    def test_search_is_tenant_scoped_read_only_and_ignores_sms_rows(self):
        self.service.suppress(self.user, self.b.customer_id)
        before = sum(op == 'transact_write_items' for op, _ in self.db.calls)
        self.assertEqual(self.service.search_customers('trumps', 'Other')['results'], [])
        result = self.service.search_customers('other-business', 'Other')['results'][0]
        self.assertEqual(result['customer_id'], self.other.customer_id)
        self.assertEqual(sum(op == 'transact_write_items' for op, _ in self.db.calls), before)
        self.assertEqual(self.service.history('trumps'), [])
        self.provider.send.assert_not_called()
    def test_result_limit_reports_total_and_keeps_all_eligibilities(self):
        customers = [self.a.model_copy(update={'customer_id': str(uuid4()), 'first_name': 'Match', 'status': 'inactive'}) for _ in range(30)]
        with patch.object(self.customers, 'list', return_value=customers):
            result = self.service.search_customers('trumps', 'Match')
        self.assertEqual(result['total_matches'], 30); self.assertEqual(len(result['results']), 25)
        self.assertTrue(all(not c['sms_eligible'] for c in result['results']))
    def test_invalid_number_missing_timestamp_and_future_consent_reasons(self):
        for change, text in [({'phone': 'invalid'}, 'Invalid'), ({'consent_timestamp': None}, 'timestamp'), ({'consent_timestamp': self.now + timedelta(days=1)}, 'timestamp')]:
            customer = self.a.model_copy(update=change)
            with patch.object(self.customers, 'list', return_value=[customer]):
                row = self.service.search_customers('trumps', 'Sarah')['results'][0]
                self.assertFalse(row['sms_eligible']); self.assertIn(text, row['ineligible_reason'])


class SMSSearchDynamoTests(SMSSearchMemoryTests):
    dynamo = True


class SMSSearchAPITests(unittest.TestCase):
    setUp = SMSAPITests.setUp
    call = SMSAPITests.call
    def test_owner_manager_search_permissions_and_safe_projection(self):
        for role in [Role.OWNER, Role.MANAGER]:
            self.verifier.verify.return_value = replace(self.user, role=role)
            status, result = self.call('GET', '/sms/customers', query='q=Sar')
            self.assertEqual(status, 200); self.assertEqual(result['results'][0]['name'], 'Sarah Fictional')
            self.assertNotIn(self.customer.phone, str(result))
            self.assertNotIn('date_of_birth', str(result))
    def test_staff_anonymous_tenant_spoofing_and_query_limit(self):
        self.assertEqual(self.call('GET', '/sms/customers', query='q=Sar', token=None)[0], 401)
        self.verifier.verify.return_value = replace(self.user, role=Role.STAFF)
        self.assertEqual(self.call('GET', '/sms/customers', query='q=Sar')[0], 403)
        self.verifier.verify.return_value = self.user
        self.assertEqual(self.call('GET', '/sms/customers', query='q=Sar&business_id=other-business')[0], 403)
        self.assertEqual(self.call('GET', '/sms/customers', query='q=' + 'a' * 101)[0], 422)
        self.verifier.verify.return_value = replace(self.user, business_id='other-business')
        self.assertEqual(self.call('GET', '/sms/customers', query='q=Sar')[1]['results'], [])
