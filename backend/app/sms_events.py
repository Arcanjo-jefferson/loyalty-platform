"""INTERNAL incoming-event processing. No public routes or live signature verifier.

Only receive() crosses the provider verification boundary. Adapter injection is
server-owned (offline tests/future integrations), never selected by request data.
Bindings and correlation registration are trusted operator/dispatch operations.
No operation sends SMS, creates customers, changes consent or releases budget.
"""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
import os
from typing import Literal
from pydantic import Field
from .sms_contracts import Contract, DeliveryStatusEvent, IncomingSMSEvent
from .sms_provider import build_provider
from .sms_repository import SMSConflict
from .sms_service import suppression_key, stamp
from .models import CustomerInput

KEYWORDS = frozenset({'STOP', 'UNSUBSCRIBE', 'CANCEL', 'END', 'QUIT'})
FINAL = frozenset({'DELIVERED', 'FAILED', 'UNDELIVERED'})
RANK = {'UNKNOWN': -1, 'ACCEPTED': 0, 'SENT': 1}


class EventRejected(ValueError):
    """Safe reason only; never include raw request, signature or provider errors."""


def digest(parts):
    return sha256(json.dumps(parts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class ProviderBinding(Contract):
    provider: Literal['twilio', 'clicksend']
    account_id: str = Field(min_length=1, max_length=128)
    receiving_number: str = Field(pattern=r'^\+[1-9][0-9]{7,14}$', repr=False)
    business_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')

    @property
    def identity(self):
        return self.provider + ':v1:' + digest([self.provider, self.account_id, self.receiving_number])


class ProviderBindings:
    def __init__(self, bindings=()):
        self.bindings = tuple(ProviderBinding.model_validate(b) for b in bindings)
        routes = [(b.provider, b.account_id, b.receiving_number) for b in self.bindings]
        if len(routes) != len(set(routes)): raise EventRejected('Ambiguous SMS provider bindings.')

    @classmethod
    def from_environment(cls):
        try:
            raw = json.loads(os.getenv('SMS_EVENT_BINDINGS_JSON', '[]'))
            if not isinstance(raw, list): raise ValueError()
            return cls(raw)
        except (ValueError, TypeError):
            raise EventRejected('Invalid SMS event bindings.') from None

    def resolve(self, provider, account, destination):
        matches = [b for b in self.bindings if (b.provider, b.account_id, b.receiving_number) == (provider, account, destination)]
        if len(matches) != 1: raise EventRejected('Unknown or ambiguous SMS provider binding.')
        return matches[0]


class SMSEvents:
    def __init__(self, sms, bindings=None, adapters=None, clock=None):
        self.sms = sms
        self.store = sms.store
        self.bindings = bindings if bindings is not None else ProviderBindings.from_environment()
        self.adapters = dict(adapters or {})
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def receive(self, kind, provider, *, body, headers, url):
        """Verify raw bytes before resolving a tenant or performing any DB operation.
        Production defaults use disabled adapters. There is no verified=True flag
        or endpoint accepting already-normalized events from untrusted callers.
        """
        if kind not in {'incoming', 'delivery'} or provider not in {'twilio', 'clicksend'}:
            raise EventRejected('Unsupported SMS event.')
        if not isinstance(body, bytes) or len(body) > 65536:
            raise EventRejected('Malformed SMS event.')
        try:
            adapter = self.adapters.get(provider) or build_provider(provider)
            event = (adapter.verify_incoming if kind == 'incoming' else adapter.verify_delivery)(body=body, headers=headers, url=url)
            expected = IncomingSMSEvent if kind == 'incoming' else DeliveryStatusEvent
            if type(event) is not expected or event.provider != provider: raise ValueError()
        except Exception:
            raise EventRejected('SMS provider event authentication or validation failed.') from None
        binding = self.bindings.resolve(provider, event.account_id, event.destination)
        if event.occurred_at > self.clock() + timedelta(minutes=5):
            raise EventRejected('Invalid SMS event timestamp.')
        return self._incoming(binding, event) if kind == 'incoming' else self._delivery(binding, event)

    def _item(self, binding, key, kind, **fields):
        return dict(business_id=binding.business_id, customer_id=key, item_type=kind, **fields)

    def _receipt(self, binding, kind, event):
        key = 'SMS_EVENT#' + digest([binding.identity, kind, event.event_id])
        fingerprint = digest(event.model_dump(mode='json'))
        old = self.store.get(binding.business_id, key)
        if old:
            if old['fingerprint'] != fingerprint: raise EventRejected('SMS event ID collision.')
            return None
        return self._item(binding, key, 'SMS_EVENT', fingerprint=fingerprint,
                          event_kind=kind, event_id=event.event_id, received_at=stamp(self.clock()), occurred_at=stamp(event.occurred_at))

    def _incoming(self, binding, event):
        try: phone = CustomerInput.normalize_phone(event.sender)
        except (ValueError, TypeError): raise EventRejected('Invalid SMS sender number.') from None
        keyword = event.body.strip().upper()
        for _ in range(8):
            receipt = self._receipt(binding, 'incoming', event)
            if receipt is None: return {'result': 'duplicate'}
            changes = [(None, receipt)]
            if keyword in KEYWORDS:
                key = suppression_key(phone)
                old = self.store.get(binding.business_id, key)
                # Preserve existing suppression evidence, even if customer was deleted.
                value = old or self._item(binding, key, 'SMS_SUPPRESSION', created_by='provider:' + binding.provider,
                    created_at=stamp(self.clock()), reason='INCOMING_OPT_OUT', keyword=keyword)
                changes.append((old, value))
            try:
                self.store.commit(binding.business_id, changes)
                return {'result': 'suppressed' if keyword in KEYWORDS else 'ignored'}
            except SMSConflict: continue
        raise EventRejected('SMS event processing conflicted. Retry the same event.')

    def _correlation_key(self, binding, provider_message_id):
        return 'SMS_MESSAGE#' + digest([binding.identity, provider_message_id])

    def register_message(self, binding, campaign_id, customer_id, provider_message_id):
        """Trusted future dispatch hook, never an API or inference from a callback.
        Atomically binds provider ID to the original campaign and recipient. Real
        dispatch is disabled; tests seed fictional submitted campaigns explicitly.
        """
        if not isinstance(provider_message_id, str) or not 1 <= len(provider_message_id) <= 256:
            raise EventRejected('Invalid provider message ID.')
        binding = self.bindings.resolve(binding.provider, binding.account_id, binding.receiving_number)
        key = self._correlation_key(binding, provider_message_id)
        for _ in range(8):
            campaign = self.sms.get(binding.business_id, campaign_id)
            if campaign['provider'] != binding.provider or campaign.get('provider_identity') != binding.identity:
                raise EventRejected('SMS campaign provider binding mismatch.')
            rows = [r for r in campaign['recipients'] if r['id'] == customer_id]
            if len(rows) != 1 or rows[0]['status'] not in {'SUBMITTING', 'UNKNOWN'}:
                raise EventRejected('SMS recipient is not submitted.')
            if rows[0].get('provider_id') not in {None, provider_message_id}:
                raise EventRejected('SMS recipient already correlated.')
            correlation = self._item(binding, key, 'SMS_MESSAGE', campaign_id=campaign_id, recipient_id=customer_id,
                provider_message_id=provider_message_id, provider_identity=binding.identity)
            old = self.store.get(binding.business_id, key)
            if old:
                if any(old[k] != v for k, v in correlation.items()): raise EventRejected('Provider message already correlated.')
                return
            changed = deepcopy(campaign)
            next(r for r in changed['recipients'] if r['id'] == customer_id)['provider_id'] = provider_message_id
            try:
                self.store.commit(binding.business_id, [(None, correlation), (campaign, changed)])
                return
            except SMSConflict: continue
        raise EventRejected('SMS correlation conflicted.')

    def _delivery(self, binding, event):
        key = self._correlation_key(binding, event.provider_message_id)
        for _ in range(8):
            receipt = self._receipt(binding, 'delivery', event)
            if receipt is None: return {'result': 'duplicate'}
            correlation = self.store.get(binding.business_id, key)
            if correlation is None or correlation['provider_identity'] != binding.identity:
                raise EventRejected('Uncorrelated SMS delivery event.')
            campaign = self.sms.get(binding.business_id, correlation['campaign_id'])
            if campaign['provider'] != binding.provider or campaign.get('provider_identity') != binding.identity:
                raise EventRejected('SMS campaign provider binding mismatch.')
            changed = deepcopy(campaign)
            rows = [r for r in changed['recipients'] if r['id'] == correlation['recipient_id']]
            if len(rows) != 1 or rows[0].get('provider_id') != event.provider_message_id:
                raise EventRejected('SMS recipient correlation mismatch.')
            row = rows[0]
            current = row.get('delivery_status', 'UNKNOWN')
            last_at = row.get('delivery_event_at')
            allowed = (row['status'] in {'SUBMITTING', 'UNKNOWN'} and current not in FINAL
                and (last_at is None or event.occurred_at >= datetime.fromisoformat(last_at))
                and (event.status in FINAL or RANK.get(event.status, -1) >= RANK.get(current, -1)))
            changes = [(None, receipt)]
            if allowed:
                row.update(delivery_status=event.status, delivery_event_at=stamp(event.occurred_at),
                           delivery_error_code=event.error_code, updated_at=stamp(self.clock()))
                changed['updated_at'] = stamp(self.clock())
                changes.append((campaign, changed))
            try:
                self.store.commit(binding.business_id, changes, checks=(correlation,))
                return {'result': 'updated' if allowed else 'ignored'}
            except SMSConflict: continue
        raise EventRejected('SMS event processing conflicted. Retry the same event.')
