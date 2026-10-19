"""Worker tests use fake repositories only; no AWS, Twilio or physical output."""
import asyncio
from copy import deepcopy
from threading import Event
import unittest
from app.sms_worker import SMSWorker
from app.sms_provider import SimulatedSMSProvider
from app.sms_service import SMSService
from app.auth import Role
from dataclasses import replace
import test_sms as fixtures


class SMSWorkerTests(unittest.TestCase):
    dynamo = False
    setUp = fixtures.SMSMemoryTests.setUp
    create = fixtures.SMSMemoryTests.create
    data = fixtures.SMSMemoryTests.data
    queue = fixtures.SMSMemoryTests.queue
    edit = fixtures.SMSMemoryTests.edit
    def test_thread_processes_confirmed_outbox_and_shuts_down(self):
        self.queue(); self.service.provider = SimulatedSMSProvider()
        complete = Event(); original = self.service.process
        def process(*args, **kwargs):
            result = original(*args, **kwargs); complete.set(); return result
        self.service.process = process
        worker = SMSWorker(self.service, ('trumps',), interval=.01)
        try:
            worker.start(); self.assertTrue(complete.wait(3))
        finally: worker.stop()
        self.assertFalse(worker.thread.is_alive())
        self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'SIMULATED')
    def test_no_confirmed_job_or_no_business_does_nothing(self):
        self.service.preview(self.user, self.data()); self.service.provider = SimulatedSMSProvider()
        worker = SMSWorker(self.service); worker.tick()
        self.assertEqual(self.service.history('trumps'), [])
        worker.notify('trumps'); worker.tick(); self.assertEqual(self.service.history('trumps'), [])
    def test_eligibility_is_still_checked(self):
        self.queue(); self.edit(self.a, marketing_consent=False); self.service.provider = SimulatedSMSProvider()
        SMSWorker(self.service, ('trumps',)).tick()
        self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'SUPPRESSED')
    def test_unknown_is_never_automatically_retried(self):
        self.queue(); self.service.provider = SimulatedSMSProvider()
        old = self.service.store.listing('trumps', 'SMS_CAMPAIGN#')[0]; updated = deepcopy(old)
        updated['recipients'][0]['status'] = 'UNKNOWN'
        self.service.store.commit('trumps', [(old, updated)])
        worker = SMSWorker(self.service, ('trumps',)); worker.tick(); worker.tick()
        self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'UNKNOWN')
    def test_non_simulated_provider_is_refused(self):
        worker = SMSWorker(self.service, ('trumps',))  # Existing fixture uses a mock provider.
        with self.assertRaises(RuntimeError): worker.tick()
        self.provider.send.assert_not_called()
    def test_recovery_uses_durable_outbox_from_another_service(self):
        self.queue()
        restored = SMSService(self.customers, clock=lambda: self.now)
        SMSWorker(restored, ('trumps',)).tick()
        self.assertEqual(restored.history('trumps')[0]['recipients'][0]['status'], 'SIMULATED')
    def test_stopping_prevents_new_processing_and_invalid_businesses_fail(self):
        self.queue(); self.service.provider = SimulatedSMSProvider()
        worker = SMSWorker(self.service, ('trumps',)); worker.stop(); worker.tick()
        self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'QUEUED')
        for business in ['!PUBLIC_QR', '', '../other']:
            with self.assertRaises(ValueError): worker.notify(business)


class SMSWorkerDynamoTests(SMSWorkerTests):
    dynamo = True


class SMSWorkerAPITests(unittest.TestCase):
    setUp = fixtures.SMSAPITests.setUp
    call = fixtures.SMSAPITests.call
    def test_confirm_registers_verified_scope_and_status_read_is_protected(self):
        _, draft = self.call('POST', '/sms/preview', {'audience': 'all', 'message': 'Hi'})
        path = '/sms/campaigns/' + draft['campaign_id']
        self.assertEqual(self.call('POST', path + '/confirm', {'confirmed': True})[0], 200)
        self.assertEqual(self.app.state.sms_worker.businesses, {'trumps'})
        self.assertEqual(self.call('GET', path)[1]['status'], 'QUEUED')
        self.verifier.verify.return_value = replace(self.user, role=Role.STAFF)
        self.assertEqual(self.call('GET', path)[0], 403)
        self.verifier.verify.return_value = replace(self.user, business_id='other-business')
        self.assertEqual(self.call('GET', path)[0], 404)
    def test_lifespan_starts_and_stops_worker_without_requests(self):
        async def lifecycle():
            async with self.app.router.lifespan_context(self.app):
                self.assertTrue(self.app.state.sms_worker.thread.is_alive())
            self.assertFalse(self.app.state.sms_worker.thread.is_alive())
        asyncio.run(lifecycle())
