"""Provider preparation regression tests: all storage, events and transports offline."""
from copy import deepcopy
from datetime import datetime, timezone
from dataclasses import replace
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from fastapi import HTTPException
from pydantic import ValidationError
from app.sms_contracts import (SendRequest, DeliveryStatusEvent, IncomingSTOPEvent,
    PermanentProviderError, UncertainProviderError, ProviderUnavailable)
from app.sms_provider import build_provider, require_simulation
from app.sms_models import SMSSettings
from app.sms_service import SMSService
from app.sms_worker import SMSWorker
import test_sms as fixtures


class ProviderContractsTests(TestCase):
    def test_factory_allowlist_and_no_live_transport(self):
        request = SendRequest(sender='Test', destination='+353831234567', body='Fictional', message_id='stable')
        self.assertEqual(build_provider('simulation').send(request).status, 'SIMULATED')
        self.assertNotIn(request.destination, repr(request)); self.assertNotIn(request.body, repr(request))
        for name in ['twilio', 'clicksend']:
            adapter = build_provider(name)
            with self.assertRaises(ProviderUnavailable): adapter.send(request)
            for method in [adapter.verify_delivery, adapter.verify_stop]:
                with self.assertRaises(ProviderUnavailable): method(body=b'{}', headers={}, url='https://invalid.test')
        for name in ['unknown', '../provider', 'Twilio', '']:
            with self.assertRaises(ValueError): build_provider(name)

    def test_flag_is_not_an_activation_switch(self):
        for flag in ['true', '1', '', 'yes', 'garbage']:
            with patch.dict('os.environ', SMS_REAL_DELIVERY_ENABLED=flag):
                with self.assertRaises(ProviderUnavailable): require_simulation('simulation')
        with patch.dict('os.environ', SMS_REAL_DELIVERY_ENABLED='false'):
            require_simulation('simulation')
            for name in ['twilio', 'clicksend']:
                with self.assertRaises(ProviderUnavailable): require_simulation(name)

    def test_environment_default_selection_and_tenant_overrides(self):
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(SMSSettings.for_business('trumps').provider, 'simulation')
        with patch.dict('os.environ', SMS_PROVIDER='clicksend', SMS_BUSINESS_SETTINGS_JSON='{"trumps":{"provider":"simulation"}}'):
            self.assertEqual(SMSSettings.for_business('trumps').provider, 'simulation')
            self.assertEqual(SMSSettings.for_business('other').provider, 'clicksend')
        with patch.dict('os.environ', SMS_PROVIDER='invalid', SMS_BUSINESS_SETTINGS_JSON='{}'):
            with self.assertRaises(ValueError): SMSSettings.for_business('trumps')

    def test_normalized_event_contracts_are_strict_and_timezone_aware(self):
        common = dict(provider='twilio', account_id='fixture-account', event_id='fixture-event', occurred_at=datetime.now(timezone.utc))
        self.assertEqual(DeliveryStatusEvent(**common, provider_message_id='fixture-message', status='DELIVERED').status, 'DELIVERED')
        stop = IncomingSTOPEvent(**common, sender='+353831234567', destination='fixture-sender')
        self.assertEqual(stop.keyword, 'STOP'); self.assertNotIn(stop.sender, repr(stop))
        for update in [dict(business_id='untrusted'), dict(occurred_at=datetime(2026, 1, 1)), dict(status='made-up')]:
            with self.assertRaises(ValidationError): DeliveryStatusEvent(**(common | dict(provider_message_id='id', status='SENT') | update))
        with self.assertRaises(ValidationError): IncomingSTOPEvent(**(stop.model_dump() | {'keyword': 'START'}))

    def test_standalone_rejects_disabled_provider_before_repository_creation(self):
        spec = spec_from_file_location('sms_runner_test', Path(__file__).parents[1] / 'scripts/run_sms_worker.py')
        runner = module_from_spec(spec); spec.loader.exec_module(runner)
        for name in ['twilio', 'clicksend']:
            with patch.dict('os.environ', SMS_PROVIDER=name, SMS_BUSINESS_SETTINGS_JSON='{}'), patch('sys.argv', ['worker', '--business', 'trumps', '--once']), patch.object(runner, 'build_repository') as repository:
                with self.assertRaises(SystemExit): runner.main()
                repository.assert_not_called()


class ProviderServiceTests(TestCase):
    dynamo = False
    setUp = fixtures.SMSMemoryTests.setUp
    create = fixtures.SMSMemoryTests.create
    data = fixtures.SMSMemoryTests.data
    queue = fixtures.SMSMemoryTests.queue

    def test_new_campaign_pins_provider_identity_and_stable_request_key(self):
        campaign = self.queue()
        stored = self.service.get('trumps', campaign['campaign_id'])
        self.assertEqual(stored['provider_identity'], 'simulation:v1')
        self.service.process('trumps'); self.service.process('trumps')
        self.assertEqual(self.provider.send.call_count, 1)
        request = self.provider.send.call_args.args[0]
        self.assertIsInstance(request, SendRequest)
        self.assertEqual(request.message_id, campaign['campaign_id'] + ':' + self.a.customer_id)
        self.assertEqual(request.destination, self.a.phone)

    def test_disabled_configuration_blocks_preview_budget_dispatch_and_worker(self):
        campaign = self.queue(); reserved = self.service.summary('trumps')['reserved_micros']
        for name in ['twilio', 'clicksend']:
            self.settings = replace(self.settings, provider=name)
            with self.assertRaises(HTTPException): self.service.preview(self.user, self.data())
            with self.assertRaises(HTTPException): self.service.process('trumps')
            self.assertEqual(self.service.summary('trumps')['reserved_micros'], reserved)
            self.assertFalse(self.service.summary('trumps')['real_delivery_enabled'])
            restored = SMSService(self.customers, settings=lambda _: self.settings)
            SMSWorker(restored, ['trumps']).tick()  # Logged safe failure, no dispatch.
        self.provider.send.assert_not_called()
        self.assertEqual(self.service.get('trumps', campaign['campaign_id'])['recipients'][0]['status'], 'QUEUED')

    def test_config_change_before_confirmation_does_not_reserve_budget(self):
        draft = self.service.preview(self.user, self.data())
        self.settings = replace(self.settings, provider='clicksend')
        with self.assertRaises(HTTPException) as error: self.service.confirm(self.user, draft['campaign_id'], True)
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.service.summary('trumps')['reserved_micros'], 0)

    def test_identity_or_sender_change_never_redirects_queued_campaign(self):
        campaign = self.queue()
        self.settings = replace(self.settings, sender='Different sender')
        self.assertEqual(self.service.process('trumps')['processed'], 0)
        self.settings = replace(self.settings, sender='Loyalty System (simulation)')
        old = self.service.get('trumps', campaign['campaign_id']); changed = deepcopy(old)
        changed['provider_identity'] = 'twilio:v1'
        self.service.store.commit('trumps', [(old, changed)])
        self.assertEqual(self.service.process('trumps')['processed'], 0)
        self.provider.send.assert_not_called()

    def test_legacy_campaigns_need_no_migration(self):
        campaign = self.queue(); old = self.service.get('trumps', campaign['campaign_id'])
        legacy = deepcopy(old); legacy.pop('provider_identity')
        self.service.store.commit('trumps', [(old, legacy)])
        self.service.process('trumps')
        self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'SIMULATED')

    def test_real_flag_cannot_enable_injected_sender_on_any_service_path(self):
        self.queue()
        with patch.dict('os.environ', SMS_REAL_DELIVERY_ENABLED='true'):
            with self.assertRaises(HTTPException): self.service.process('trumps')
            with self.assertRaises(HTTPException): self.service.preview(self.user, self.data())
        self.provider.send.assert_not_called()

    def test_permanent_error_is_sanitized_and_never_retried(self):
        self.queue(); self.provider.send.side_effect = PermanentProviderError('private-provider-payload')
        self.service.process('trumps'); self.service.process('trumps')
        result = self.service.history('trumps')[0]['recipients'][0]
        self.assertEqual(result['status'], 'FAILED'); self.assertNotIn('private-provider-payload', str(result))
        self.assertEqual(self.provider.send.call_count, 1)

    def test_uncertain_error_never_retries_or_fails_over(self):
        self.queue(); self.provider.send.side_effect = UncertainProviderError('private-provider-payload')
        self.service.process('trumps'); self.service.process('trumps')
        self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'UNKNOWN')
        self.assertEqual(self.provider.send.call_count, 1)


class ProviderDynamoTests(ProviderServiceTests):
    dynamo = True
