"""Owner/Manager manual campaigns only. Does not touch reward/visit/print policy."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from uuid import uuid4
import re
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from .models import CustomerInput
from .sms_models import SMSSettings, SMSRecipientHistory, estimate, render
from .sms_repository import SMSRepository, SMSConflict
from .sms_provider import build_provider, require_simulation, provider_identity
from .sms_contracts import SendRequest, SafeRetry, PermanentProviderError, ProviderUnavailable

ZONE = ZoneInfo('Europe/Dublin')
TERMINAL = {'SIMULATED', 'SUPPRESSED', 'FAILED', 'UNKNOWN'}


def suppression_key(phone): return 'SMS_SUPPRESS#' + sha256(phone.encode()).hexdigest()


def stamp(value): return value.astimezone(timezone.utc).isoformat()


class SMSService:
    def __init__(self, customers, provider=None, clock=None, settings=None):
        self.customers = customers
        self.store = SMSRepository(customers.repository)
        self.provider = provider  # Optional dependency injection for offline tests only.
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.settings_factory = settings or SMSSettings.for_business

    def settings(self, business):
        try: return self.settings_factory(business)
        except (ValueError, TypeError): raise HTTPException(503, 'SMS simulation settings are unavailable.') from None

    def available_provider(self, settings):
        try:
            require_simulation(settings.provider)
            return self.provider if self.provider is not None else build_provider(settings.provider)
        except (ValueError, ProviderUnavailable):
            raise HTTPException(503, 'SMS provider is disabled. Only simulation is available.') from None

    def provider_matches(self, campaign, settings):
        # f883dd2 records already stored provider=simulation; additive version defaults
        # only apply to those legacy records, never infer a live provider.
        identity = campaign.get('provider_identity', 'simulation:v1')
        return (campaign.get('provider') == settings.provider
                and identity == provider_identity(settings.provider)
                and campaign['sender'] == settings.sender)

    def eligibility_reason(self, customer):
        if customer is None: return 'Customer is unavailable.'
        if customer.status != 'active': return 'Customer is inactive.'
        try: valid = CustomerInput.normalize_phone(customer.phone) == customer.phone
        except (ValueError, TypeError): valid = False
        if not valid: return 'Invalid Irish mobile number.'
        if not customer.marketing_consent: return 'Marketing consent has not been granted.'
        if (customer.consent_timestamp is None or customer.consent_timestamp.tzinfo is None
                or customer.consent_timestamp > self.clock()):
            return 'Marketing consent timestamp is missing or invalid.'
        if self.store.get(customer.business_id, suppression_key(customer.phone)) is not None:
            return 'Customer has opted out of SMS.'
        return None

    def eligible(self, customer):
        return self.eligibility_reason(customer) is None

    def search_customers(self, business, query):
        text = ' '.join(query.casefold().split())
        if not text: return {'results': [], 'total_matches': 0}
        compact = re.sub(r'[ ().-]', '', query.strip())
        phone = compact
        for candidate in [compact, '0' + compact, '+' + compact]:
            try:
                phone = CustomerInput.normalize_phone(candidate)
                break
            except ValueError: pass
        else:
            if re.fullmatch(r'08[35679][0-9]*', compact): phone = compact[1:]
        matches = []
        # Reuse the existing paginated, tenant-scoped customer repository Query.
        # Do not filter out ineligible customers: explain why they cannot be selected.
        for customer in sorted(self.customers.list(business), key=lambda c: (c.first_name.casefold(), c.last_name.casefold(), c.customer_id)):
            name = f'{customer.first_name} {customer.last_name}'
            if text not in ' '.join(name.casefold().split()) and phone not in customer.phone and text not in customer.phone:
                continue
            reason = self.eligibility_reason(customer)
            matches.append(dict(customer_id=customer.customer_id, name=name, first_name=customer.first_name,
                masked_phone=('+' if customer.phone.startswith('+') else '') + '•••••••' + customer.phone[-4:],
                sms_eligible=reason is None, ineligible_reason=reason))
        return {'results': matches[:25], 'total_matches': len(matches)}

    def audience(self, business, mode, customer_id):
        customers = [self.customers.get(business, customer_id)] if mode == 'individual' else self.customers.list(business)
        eligible, seen = [], set()
        for customer in sorted(customers, key=lambda c: c.customer_id):
            if self.eligible(customer) and customer.phone not in seen:
                seen.add(customer.phone)
                eligible.append(dict(id=customer.customer_id, phone=customer.phone,
                    first_name=customer.first_name, name=f'{customer.first_name} {customer.last_name}',
                    consent_timestamp=stamp(customer.consent_timestamp), customer_revision=stamp(customer.updated_at)))
        if len(eligible) > 200: raise HTTPException(422, 'Select at most 200 eligible recipients per campaign.')
        return eligible, len(customers) - len(eligible)

    def totals(self, rows, message, settings):
        segments = 0
        for row in rows:
            text = render(message, row['first_name'])
            if len(text) > 1600: raise HTTPException(422, 'Personalised messages must be at most 1600 characters.')
            segments += estimate(text)['segments']
        return dict(recipient_count=len(rows), total_segments=segments,
                    estimated_cost_micros=segments * settings.segment_price_micros)

    def view(self, record):
        rows = []
        for row in record['recipients']:
            body = render(record['message'], row['first_name'])
            rows.append(SMSRecipientHistory(**{**{k: row.get(k) for k in ['id', 'name', 'phone', 'status', 'updated_at', 'provider_id', 'reason', 'consent_timestamp']},
                         'body': body, **estimate(body), 'consent_decision': row.get('consent_decision', 'EXPLICIT_OPT_IN_AT_QUEUE' if record['status'] != 'DRAFT' else 'PREVIEW_ONLY')}).model_dump())
        return {k: record[k] for k in ['campaign_id', 'message', 'audience', 'created_by', 'created_at', 'updated_at', 'status',
                'sender', 'provider', 'recipient_count', 'total_segments', 'estimated_cost_micros', 'expires_at', 'excluded_count']} | {
                    'recipients': rows, 'currency': 'EUR', 'price_is_illustrative': True}

    def preview(self, user, data):
        settings = self.settings(user.business_id)
        self.available_provider(settings)
        rows, excluded = self.audience(user.business_id, data.audience, str(data.customer_id) if data.customer_id else None)
        now = self.clock(); identity = str(uuid4())
        record = dict(business_id=user.business_id, customer_id='SMS_CAMPAIGN#' + identity,
            item_type='SMS_CAMPAIGN', campaign_id=identity, message=data.message, audience=data.audience,
            selected_customer_id=str(data.customer_id) if data.customer_id else None,
            created_by=user.subject, created_at=stamp(now), updated_at=stamp(now), status='DRAFT',
            expires_at=stamp(now + timedelta(minutes=15)), sender=settings.sender, provider=settings.provider, provider_identity=provider_identity(settings.provider),
            segment_price_micros=settings.segment_price_micros, excluded_count=excluded,
            recipients=[r | dict(status='DRAFT', updated_at=stamp(now), attempts=0) for r in rows],
            **self.totals(rows, data.message, settings))
        self.store.commit(user.business_id, [(None, record)])
        return self.view(record)

    def get(self, business, identity):
        value = self.store.get(business, 'SMS_CAMPAIGN#' + str(identity))
        if not value: raise HTTPException(404, 'SMS campaign not found.')
        return value

    def confirm(self, user, identity, confirmed):
        if not confirmed: raise HTTPException(422, 'Explicitly confirm simulated sending.')
        for _ in range(5):
            old = self.get(user.business_id, identity)
            # Idempotent even after expiry, worker progress, or a later budget change.
            if old['status'] != 'DRAFT': return self.view(old)
            if old['created_by'] != user.subject: raise HTTPException(403, 'Only the preview creator may confirm it.')
            now = self.clock()
            if now >= datetime.fromisoformat(old['expires_at']): raise HTTPException(409, 'Preview expired. Preview the message again.')
            settings = self.settings(user.business_id)
            if not self.provider_matches(old, settings):
                raise HTTPException(409, 'SMS provider settings changed. Preview the message again.')
            self.available_provider(settings)
            rows, _ = self.audience(user.business_id, old['audience'], old['selected_customer_id'])
            previous = [{k: row[k] for k in ['id', 'phone', 'first_name', 'name', 'consent_timestamp', 'customer_revision']} for row in old['recipients']]
            totals = self.totals(rows, old['message'], settings)
            if rows != previous or settings.sender != old['sender'] or settings.segment_price_micros != old['segment_price_micros']:
                raise HTTPException(409, 'Recipients or SMS settings changed. Preview the message again.')
            if not rows: raise HTTPException(422, 'No eligible recipients. Check consent, suppression and customer status.')
            month = now.astimezone(ZONE).strftime('%Y-%m')
            key = 'SMS_BUDGET#' + month
            budget = self.store.get(user.business_id, key)
            reserved = int(budget['reserved_micros']) if budget else 0
            if reserved + totals['estimated_cost_micros'] > settings.monthly_limit_micros:
                raise HTTPException(409, 'Monthly SMS spending limit exceeded. Nothing was queued.')
            record = deepcopy(old)
            record.update(status='QUEUED', updated_at=stamp(now), confirmed_by=user.subject, budget_month=month)
            for row in record['recipients']: row.update(status='QUEUED', updated_at=stamp(now))
            ledger = dict(business_id=user.business_id, customer_id=key, item_type='SMS_BUDGET',
                          reserved_micros=reserved + totals['estimated_cost_micros'])
            try:
                self.store.commit(user.business_id, [(old, record), (budget, ledger)])
                return self.view(record)
            except SMSConflict: continue
        raise HTTPException(409, 'SMS queue changed. Retry the same confirmation.')

    def history(self, business):
        records = sorted(self.store.listing(business, 'SMS_CAMPAIGN#'), key=lambda r: (r['created_at'], r['campaign_id']), reverse=True)
        # UI is bounded; discovery uses the full internal Query, including older queued jobs.
        return [self.view(r) for r in records if r['status'] != 'DRAFT'][:100]

    def summary(self, business):
        settings = self.settings(business)
        month = self.clock().astimezone(ZONE).strftime('%Y-%m')
        ledger = self.store.get(business, 'SMS_BUDGET#' + month)
        return dict(provider=settings.provider, real_delivery_enabled=False, sender=settings.sender, currency='EUR',
                    monthly_limit_micros=settings.monthly_limit_micros, reserved_micros=int(ledger['reserved_micros']) if ledger else 0,
                    segment_price_micros=settings.segment_price_micros, budget_month=month, price_is_illustrative=True)

    def suppress(self, user, customer_id):
        customer = self.customers.get(user.business_id, str(customer_id))
        key = suppression_key(customer.phone)
        old = self.store.get(user.business_id, key)
        if not old:
            try:
                self.store.commit(user.business_id, [(None, dict(business_id=user.business_id, customer_id=key,
                    item_type='SMS_SUPPRESSION', created_by=user.subject, created_at=stamp(self.clock()), reason='MANUAL_OPT_OUT'))])
            except SMSConflict: pass  # Existing suppression is equally restrictive.
        return {'suppressed': True}

    def process(self, business, limit=200, should_stop=lambda: False):
        """Durable manual simulation runner; same operation used by the standalone worker.
        No message body/destination is logged. SUBMITTING is a permanent no-replay fence.
        """
        settings = self.settings(business)
        provider = self.available_provider(settings)
        processed = 0
        for campaign in self.store.listing(business, 'SMS_CAMPAIGN#'):
            if campaign['status'] == 'DRAFT': continue
            for index in range(len(campaign['recipients'])):
                if processed >= limit or should_stop(): return {'processed': processed, 'provider': 'simulation'}
                old = self.get(business, campaign['campaign_id'])
                row = old['recipients'][index]
                now = self.clock()
                if row['status'] in TERMINAL: continue
                if row['status'] == 'SUBMITTING':
                    if now >= datetime.fromisoformat(row['lease_until']):
                        self._finish(old, index, 'UNKNOWN', reason='SUBMISSION_OUTCOME_UNKNOWN')
                    continue
                if not self.provider_matches(old, settings): continue  # Never reroute queued work.
                if old.get('budget_month') != now.astimezone(ZONE).strftime('%Y-%m'):
                    self._finish(old, index, 'SUPPRESSED', reason='BUDGET_MONTH_CLOSED')
                    continue
                if row.get('retry_at') and now < datetime.fromisoformat(row['retry_at']): continue
                current = self.customers.repository.get(business, row['id'])
                if (not self.eligible(current) or current.phone != row['phone']
                        or stamp(current.consent_timestamp) != row['consent_timestamp']):
                    self._finish(old, index, 'SUPPRESSED', reason='ELIGIBILITY_CHANGED')
                    continue
                claimed = deepcopy(old)
                target = claimed['recipients'][index]
                target.update(status='SUBMITTING', claim_id=str(uuid4()), attempts=int(row['attempts']) + 1,
                              lease_until=stamp(now + timedelta(minutes=2)), updated_at=stamp(now),
                              consent_decision='EXPLICIT_OPT_IN_RECHECKED', dispatch_customer_revision=stamp(current.updated_at))
                claimed['updated_at'] = stamp(now)
                try: self.store.commit(business, [(old, claimed)], customer=current, absent=suppression_key(current.phone))
                except SMSConflict: continue
                processed += 1
                fence = self.get(business, old['campaign_id'])
                if (fence['recipients'][index].get('claim_id') != target['claim_id']
                        or fence['recipients'][index]['status'] != 'SUBMITTING'
                        or self.clock() >= datetime.fromisoformat(target['lease_until'])):
                    continue
                try:
                    # Recheck after winning the atomic fence, immediately before invoking provider.
                    latest = self.customers.repository.get(business, row['id'])
                    if not self.eligible(latest) or latest.phone != row['phone'] or stamp(latest.consent_timestamp) != row['consent_timestamp']:
                        self._finish(fence, index, 'SUPPRESSED', reason='ELIGIBILITY_CHANGED')
                        continue
                    self.available_provider(settings)  # Recheck the hard gate before submission.
                    delivery = provider.send(SendRequest(sender=old['sender'], destination=row['phone'],
                        body=render(old['message'], row['first_name']), message_id=old['campaign_id'] + ':' + row['id']))
                    # Only the simulator is supported, never claim handset delivery.
                    if delivery.status != 'SIMULATED': raise ValueError('Unexpected provider status')
                except PermanentProviderError:
                    self._finish(fence, index, 'FAILED', reason='PROVIDER_REJECTED')
                except SafeRetry:
                    status = 'FAILED' if target['attempts'] >= 3 else 'RETRYABLE'
                    self._finish(fence, index, status, reason='SAFE_PRE_SUBMIT_FAILURE', retry_at=stamp(now + timedelta(seconds=30)))
                except Exception:
                    self._finish(fence, index, 'UNKNOWN', reason='SUBMISSION_OUTCOME_UNKNOWN')
                else:
                    self._finish(fence, index, 'SIMULATED', provider_id=delivery.provider_id)
        return {'processed': processed, 'provider': 'simulation'}

    def _finish(self, previous, index, status, **fields):
        expected = previous['recipients'][index]
        for _ in range(5):
            value = deepcopy(previous)
            at = stamp(self.clock())
            value['recipients'][index].update(status=status, updated_at=at, **fields)
            value['updated_at'] = at
            value['status'] = 'FINISHED' if all(r['status'] in TERMINAL for r in value['recipients']) else 'QUEUED'
            try:
                self.store.commit(value['business_id'], [(previous, value)])
                return
            except SMSConflict:
                previous = self.get(value['business_id'], value['campaign_id'])
                if previous['recipients'][index] != expected: return
        # Persisted SUBMITTING fence is later reconciled to UNKNOWN, never replayed.
