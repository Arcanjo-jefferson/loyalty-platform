"""No real providers/signatures/network: injected verifier is an offline test double."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import json
import unittest
from unittest.mock import patch
from botocore.exceptions import ClientError
from app.sms_contracts import IncomingSMSEvent, DeliveryStatusEvent
from app.sms_events import SMSEvents, ProviderBinding, ProviderBindings, EventRejected
from app.sms_repository import SMSConflict
from app.repository import StorageUnavailable
from app.sms_service import suppression_key
import test_sms as fixtures


class OfflineVerifier:
    """Represents a future verified adapter; NOT a signature implementation."""
    def parse(self, model, **request):
        if request['headers'].get('fixture-auth') != 'valid': raise ValueError('private-invalid-signature')
        return model.model_validate_json(request['body'])
    def verify_incoming(self, **request): return self.parse(IncomingSMSEvent, **request)
    def verify_delivery(self, **request): return self.parse(DeliveryStatusEvent, **request)


class EventTests(unittest.TestCase):
    dynamo = False
    create = fixtures.SMSMemoryTests.create
    data = fixtures.SMSMemoryTests.data
    queue = fixtures.SMSMemoryTests.queue
    edit = fixtures.SMSMemoryTests.edit
    def setUp(self):
        fixtures.SMSMemoryTests.setUp(self)
        self.binding = ProviderBinding(provider='twilio', account_id='fixture-account', receiving_number='+353871111111', business_id='trumps')
        self.other_binding = self.binding.model_copy(update={'receiving_number': '+353871111112', 'business_id': 'other-business'})
        self.events = SMSEvents(self.service, ProviderBindings([self.binding, self.other_binding]),
                                {'twilio': OfflineVerifier()}, clock=lambda: self.now)

    def event(self, kind='incoming', **changes):
        fields = dict(provider='twilio', account_id=self.binding.account_id, event_id='event-1',
                      occurred_at=self.now.isoformat(), destination=self.binding.receiving_number)
        fields.update(dict(sender='0831234567', body=' STOP ') if kind == 'incoming' else dict(provider_message_id='provider-message', status='DELIVERED'))
        return fields | changes

    def receive(self, event=None, kind='incoming', headers=None):
        return self.events.receive(kind, 'twilio', body=json.dumps(event or self.event(kind)).encode(),
                                   headers=headers if headers is not None else {'fixture-auth': 'valid'}, url='https://fixture.invalid')

    def rows(self, prefix='SMS_EVENT#', business='trumps'):
        return self.service.store.listing(business, prefix)

    def submitted(self):
        queued = self.queue(); old = self.service.get('trumps', queued['campaign_id']); updated = deepcopy(old)
        updated.update(provider='twilio', provider_identity=self.binding.identity, status='FINISHED')
        updated['recipients'][0]['status'] = 'UNKNOWN'
        self.service.store.commit('trumps', [(old, updated)])
        self.events.register_message(self.binding, queued['campaign_id'], self.a.customer_id, 'provider-message')
        return queued['campaign_id']

    def test_all_keywords_case_whitespace_and_consent_not_changed(self):
        for i, word in enumerate(['STOP', 'unsubscribe', ' CaNcEl ', '\nEND\t', 'quit']):
            self.assertEqual(self.receive(self.event(event_id=str(i), body=word))['result'], 'suppressed')
        self.assertEqual(len(self.rows()), 5)
        self.assertTrue(self.customers.get('trumps', self.a.customer_id).marketing_consent)
        self.assertFalse(self.service.eligible(self.a)); self.provider.send.assert_not_called()
        self.assertEqual(len(self.rows('SMS_SUPPRESS#')), 1)

    def test_only_entire_keywords_match(self):
        for i, word in enumerate(['stop please', 'nonstop', 'STOP!', '', 'start']):
            self.assertEqual(self.receive(self.event(event_id=str(i), body=word))['result'], 'ignored')
        self.assertTrue(self.service.eligible(self.a)); self.assertEqual(len(self.rows('SMS_SUPPRESS#')), 0)

    def test_duplicates_are_persistent_and_conflicting_id_reuse_rejected(self):
        self.receive(); before = self.rows('SMS_SUPPRESS#')
        restored = SMSEvents(self.service, self.events.bindings, {'twilio': OfflineVerifier()}, clock=lambda: self.now)
        self.events = restored
        self.assertEqual(self.receive()['result'], 'duplicate'); self.assertEqual(len(self.rows()), 1)
        self.assertEqual(before, self.rows('SMS_SUPPRESS#'))
        with self.assertRaises(EventRejected): self.receive(self.event(body='QUIT'))

    def test_consent_edits_cannot_clear_suppression(self):
        self.receive(); self.edit(self.a, marketing_consent=False); self.edit(self.a, marketing_consent=True)
        self.assertEqual(self.service.preview(self.user, self.data())['recipient_count'], 0)

    def test_deleted_customer_and_reregistered_phone_remain_suppressed(self):
        # No production delete endpoint is added. Remove fixture customer only.
        if self.dynamo:
            self.db.items.pop(('trumps', self.a.customer_id))
            for key, value in list(self.db.items.items()):
                if key[0] == 'trumps' and value.get('owner_customer_id') == self.a.customer_id: self.db.items.pop(key)
        else:
            self.repo._customers.pop(('trumps', self.a.customer_id))
        self.receive()  # Customer does not exist when opt-out arrives.
        replacement = self.create('New Fictional', '0831234567')
        self.assertFalse(self.service.eligible(replacement)); self.assertEqual(len(self.rows('SMS_SUPPRESS#')), 1)

    def test_missing_customer_phone_is_suppressed_without_creation(self):
        count = len(self.repo.list('trumps'))
        self.receive(self.event(sender='+353891234567'))
        self.assertIsNotNone(self.service.store.get('trumps', suppression_key('+353891234567')))
        self.assertEqual(len(self.repo.list('trumps')), count)

    def test_authentication_validation_and_live_adapters_reject_before_writes(self):
        for headers in [{}, {'fixture-auth': 'invalid'}]:
            with self.assertRaises(EventRejected) as error: self.receive(headers=headers)
            self.assertNotIn('private-invalid-signature', str(error.exception))
        for update in [dict(business_id='other-business'), dict(provider='clicksend'), dict(sender='bad'), dict(occurred_at='bad'), dict(occurred_at=(self.now + timedelta(days=1)).isoformat())]:
            with self.assertRaises(EventRejected): self.receive(self.event(**update))
        default = SMSEvents(self.service, self.events.bindings)
        for provider in ['twilio', 'clicksend']:
            with self.assertRaises(EventRejected): default.receive('incoming', provider, body=b'{}', headers={}, url='https://invalid.test')
        self.assertEqual(self.rows(), []); self.assertEqual(self.rows('SMS_SUPPRESS#'), [])

    def test_unknown_and_ambiguous_bindings_fail_closed(self):
        with self.assertRaises(EventRejected): ProviderBindings([self.binding, self.binding.model_copy(update={'business_id': 'other-business'})])
        for update in [dict(account_id='foreign'), dict(destination='+353871111113')]:
            with self.assertRaises(EventRejected): self.receive(self.event(**update))
        self.assertEqual(self.rows(), [])

    def test_tenant_scope_is_resolved_from_verified_account_and_destination(self):
        self.receive(self.event(destination=self.other_binding.receiving_number))
        self.assertTrue(self.service.eligible(self.a)); self.assertFalse(self.service.eligible(self.other))
        self.assertEqual(len(self.rows()), 0); self.assertEqual(len(self.rows(business='other-business')), 1)

    def test_concurrent_optouts_apply_one_receipt_and_one_suppression(self):
        with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(lambda _: self.receive(), range(4)))
        self.assertEqual(sum(r['result'] == 'suppressed' for r in results), 1)
        self.assertEqual(len(self.rows()), 1); self.assertEqual(len(self.rows('SMS_SUPPRESS#')), 1)

    def test_failed_transaction_leaves_no_receipt_or_suppression(self):
        with patch.object(self.service.store, 'commit', side_effect=StorageUnavailable):
            with self.assertRaises(StorageUnavailable): self.receive()
        self.assertEqual(self.rows(), []); self.assertEqual(self.rows('SMS_SUPPRESS#'), [])
        self.assertEqual(self.receive()['result'], 'suppressed')

    def test_delivery_correlation_and_unknown_resolution_never_resends(self):
        campaign = self.submitted()
        self.assertEqual(self.receive(self.event('delivery'), 'delivery')['result'], 'updated')
        stored = self.service.get('trumps', campaign)['recipients'][0]
        self.assertEqual(stored['status'], 'UNKNOWN'); self.assertEqual(stored['delivery_status'], 'DELIVERED')
        self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'DELIVERED')
        self.service.process('trumps'); self.provider.send.assert_not_called()

    def test_duplicate_and_out_of_order_delivery_cannot_reverse_terminal(self):
        self.submitted(); delivered = self.event('delivery')
        self.receive(delivered, 'delivery')
        self.assertEqual(self.receive(delivered, 'delivery')['result'], 'duplicate')
        for i, status in enumerate(['SENT', 'ACCEPTED', 'UNKNOWN', 'FAILED', 'UNDELIVERED']):
            self.assertEqual(self.receive(self.event('delivery', event_id=str(i), status=status), 'delivery')['result'], 'ignored')
        self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'DELIVERED')

    def test_progression_and_older_events(self):
        self.submitted()
        for i, status in enumerate(['ACCEPTED', 'SENT']):
            self.assertEqual(self.receive(self.event('delivery', event_id=str(i), status=status), 'delivery')['result'], 'updated')
        self.assertEqual(self.receive(self.event('delivery', event_id='old', occurred_at=(self.now - timedelta(minutes=1)).isoformat()), 'delivery')['result'], 'ignored')
        self.assertEqual(self.receive(self.event('delivery', event_id='regress', status='ACCEPTED'), 'delivery')['result'], 'ignored')
        self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'SENT')

    def test_failed_is_terminal_and_not_replaced_by_delivered(self):
        self.submitted(); self.receive(self.event('delivery', status='FAILED'), 'delivery')
        self.assertEqual(self.receive(self.event('delivery', event_id='late'), 'delivery')['result'], 'ignored')
        self.assertEqual(self.service.history('trumps')[0]['recipients'][0]['status'], 'FAILED')

    def test_uncorrelated_cross_tenant_and_simulation_callbacks_rejected(self):
        campaign = self.queue()
        with self.assertRaises(EventRejected): self.events.register_message(self.binding, campaign['campaign_id'], self.a.customer_id, 'id')
        with self.assertRaises(EventRejected): self.receive(self.event('delivery'), 'delivery')
        self.submitted()
        with self.assertRaises(EventRejected): self.receive(self.event('delivery', destination=self.other_binding.receiving_number), 'delivery')
        self.assertEqual(self.rows(), []); self.assertEqual(self.service.view(self.service.get('trumps', campaign['campaign_id']))['recipients'][0]['status'], 'QUEUED')

    def test_delivery_transaction_failure_is_atomic_and_retryable(self):
        campaign = self.submitted()
        with patch.object(self.service.store, 'commit', side_effect=StorageUnavailable):
            with self.assertRaises(StorageUnavailable): self.receive(self.event('delivery'), 'delivery')
        self.assertEqual(self.rows(), [])
        self.assertNotIn('delivery_status', self.service.get('trumps', campaign)['recipients'][0])
        self.assertEqual(self.receive(self.event('delivery'), 'delivery')['result'], 'updated')

    def test_concurrent_delivery_callbacks_and_correlations(self):
        campaign = self.submitted()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: self.events.register_message(self.binding, campaign, self.a.customer_id, 'provider-message'), range(4)))
            results = list(pool.map(lambda _: self.receive(self.event('delivery'), 'delivery'), range(4)))
        self.assertEqual(sum(r['result'] == 'updated' for r in results), 1)
        self.assertEqual(len(self.rows()), 1); self.assertEqual(len(self.rows('SMS_MESSAGE#')), 1)

    def test_repository_conflict_retries_without_partial_updates(self):
        original = self.service.store.commit
        calls = []
        def conflict_once(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1: raise SMSConflict()
            return original(*args, **kwargs)
        with patch.object(self.service.store, 'commit', side_effect=conflict_once):
            self.receive(); self.assertEqual(len(calls), 2)
        self.assertEqual(len(self.rows()), 1); self.assertEqual(len(self.rows('SMS_SUPPRESS#')), 1)

    def test_existing_suppression_survives_customer_deletion(self):
        self.receive(); saved = self.rows('SMS_SUPPRESS#')
        if self.dynamo: self.db.items.pop(('trumps', self.a.customer_id))
        else: self.repo._customers.pop(('trumps', self.a.customer_id))
        self.assertEqual(self.rows('SMS_SUPPRESS#'), saved)
        self.receive(self.event(event_id='again'))
        self.assertEqual(self.rows('SMS_SUPPRESS#')[0]['created_at'], saved[0]['created_at'])

    def test_correlation_cannot_be_reassigned_and_event_rows_are_internal(self):
        campaign = self.submitted()
        with self.assertRaises(EventRejected):
            self.events.register_message(self.binding, campaign, self.b.customer_id, 'provider-message')
        self.receive(self.event('delivery'), 'delivery'); self.receive()
        self.assertEqual(len(self.repo.list('trumps')), 2)
        for item in self.rows() + self.rows('SMS_MESSAGE#'):
            self.assertIsNone(self.repo.get('trumps', item['customer_id']))

    def test_malformed_oversized_events_and_unknown_kinds_do_not_write(self):
        for kind, body in [('incoming', b'{'), ('incoming', b'x' * 65537), ('invalid', b'{}')]:
            with self.assertRaises(EventRejected):
                self.events.receive(kind, 'twilio', body=body, headers={'fixture-auth': 'valid'}, url='https://fixture.invalid')
        self.assertEqual(self.rows(), [])

    def test_environment_bindings_fail_closed_and_do_not_accept_payload_tenants(self):
        for config in ['{}', 'bad-json', json.dumps([self.binding.model_dump(), self.binding.model_dump()])]:
            with patch.dict('os.environ', SMS_EVENT_BINDINGS_JSON=config):
                with self.assertRaises(EventRejected): ProviderBindings.from_environment()
        with patch.dict('os.environ', SMS_EVENT_BINDINGS_JSON=json.dumps([self.binding.model_dump()])):
            self.assertEqual(ProviderBindings.from_environment().resolve('twilio', 'fixture-account', self.binding.receiving_number).business_id, 'trumps')


class EventDynamoTests(EventTests):
    dynamo = True
    def test_dynamodb_failure_does_not_consume_event(self):
        self.db.injected_errors.append(ClientError({'Error': {'Code': 'InternalServerError'}}, 'TransactWriteItems'))
        with self.assertRaises(StorageUnavailable): self.receive()
        self.assertEqual(self.rows(), []); self.assertEqual(self.rows('SMS_SUPPRESS#'), [])
        self.receive(); self.assertEqual(len(self.rows()), 1)

    def test_dynamodb_delivery_failure_keeps_receipt_and_status_atomic(self):
        campaign = self.submitted()
        self.db.injected_errors.append(ClientError({'Error': {'Code': 'InternalServerError'}}, 'TransactWriteItems'))
        with self.assertRaises(StorageUnavailable): self.receive(self.event('delivery'), 'delivery')
        self.assertEqual(self.rows(), [])
        self.assertNotIn('delivery_status', self.service.get('trumps', campaign)['recipients'][0])
        self.receive(self.event('delivery'), 'delivery')
        self.assertEqual(len(self.rows()), 1)

    def test_dynamodb_correlation_failure_cannot_partially_bind_message(self):
        queued = self.queue(); old = self.service.get('trumps', queued['campaign_id']); updated = deepcopy(old)
        updated.update(provider='twilio', provider_identity=self.binding.identity)
        updated['recipients'][0]['status'] = 'UNKNOWN'
        self.service.store.commit('trumps', [(old, updated)])
        self.db.injected_errors.append(ClientError({'Error': {'Code': 'InternalServerError'}}, 'TransactWriteItems'))
        with self.assertRaises(StorageUnavailable):
            self.events.register_message(self.binding, queued['campaign_id'], self.a.customer_id, 'provider-message')
        self.assertEqual(self.rows('SMS_MESSAGE#'), [])
        self.assertIsNone(self.service.get('trumps', queued['campaign_id'])['recipients'][0].get('provider_id'))


class EventAPIBoundaryTests(unittest.TestCase):
    setUp = fixtures.SMSAPITests.setUp
    call = fixtures.SMSAPITests.call

    def test_public_webhook_routes_are_not_exposed(self):
        for path in ['/sms/webhooks/twilio', '/sms/webhooks/clicksend', '/sms/events']:
            self.assertEqual(self.call('POST', path, {}, token=None)[0], 404)
        with self.assertRaises(EventRejected):
            self.app.state.sms_events.receive('incoming', 'twilio', body=b'{}', headers={}, url='https://fixture.invalid')
        self.assertEqual(self.app.state.sms_service.store.listing('trumps', 'SMS_EVENT#'), [])
