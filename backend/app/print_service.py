"""Authenticated human administration now; future device authorization is separate."""
from datetime import datetime, timezone
from uuid import uuid4
from .print_models import PrintJobNotFound, PrintJobConflict, PrintAudit
from .print_lifecycle import transition, effective_status, change
from .tickets import clean_text


def job_view(job, now, *, detailed=False, include_token=False):
    fields = ['print_job_id', 'source_visit_id', 'customer_id', 'ticket_type', 'source_entry_id', 'voucher_id',
              'created_at', 'updated_at', 'attempt_count', 'printed_at', 'last_error', 'reprint_of']
    data = job.model_dump(mode='json')
    result = {field: data[field] for field in fields}
    result['status'] = effective_status(job, now)
    result['display_status'] = {'PENDING': 'Queued', 'COMPLETED': 'Printed', 'CLAIMED': 'Claimed', 'PRINTING': 'Printing',
                              'UNCERTAIN': 'Uncertain — operator review required', 'FAILED': 'Failed', 'RETRYABLE': 'Retryable'}[result['status']]
    if detailed:
        result.update(ticket=data['ticket'], audit=data['audit'], reprint_reason=job.reprint_reason,
                      requested_by=job.requested_by, claimed_by=job.claimed_by, lease_until=data['lease_until'])
    if include_token: result['claim_token'] = job.claim_token
    return result


class PrintService:
    def __init__(self, customers, clock=None):
        self.customers, self.repository = customers, customers.repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def listing(self, user, *, customer_id=None, visit_id=None, review=False):
        if customer_id: self.customers.get(user.business_id, customer_id)
        jobs = self.repository.print_jobs(user.business_id, customer_id, visit_id)
        now = self.clock()
        return [job_view(job, now) for job in jobs
                if not review or effective_status(job, now) in {'FAILED', 'UNCERTAIN', 'RETRYABLE'}]

    def detail(self, user, job_id):
        return job_view(self.repository.get_print_job(user.business_id, job_id), self.clock(), detailed=True)

    def action(self, user, job_id, action, token=None):
        original = self.repository.get_print_job(user.business_id, job_id)
        now = self.clock()
        updated = transition(original, action, now, user.subject, token)
        self.repository.save_print_change(original, updated)
        return job_view(updated, now, detailed=True, include_token=action == 'claim')

    def reprint(self, user, job_id, request_id, reason):
        original = self.repository.get_print_job(user.business_id, job_id)
        if original.reprint_of: raise PrintJobConflict('Request reprints from the original job, not another reprint.')
        reason = clean_text(reason)
        if len(reason) < 5: raise PrintJobConflict('Provide a meaningful reprint audit reason.')
        new_id = original.print_job_id + '.R' + str(request_id)
        try:
            existing = self.repository.get_print_job(user.business_id, new_id)
            if existing.reprint_of == original.print_job_id and existing.requested_by == user.subject and existing.reprint_reason == reason:
                return job_view(existing, self.clock(), detailed=True)
            raise PrintJobConflict('Reprint request identity was already used.')
        except PrintJobNotFound: pass
        now = self.clock()
        status = effective_status(original, now)
        if status not in {'COMPLETED', 'FAILED', 'UNCERTAIN'}:
            raise PrintJobConflict('Only completed, failed or uncertain jobs may be explicitly reprinted.')
        # Record operator authorization on original and child in one transaction.
        parent = change(original, now, user.subject, 'REPRINT_REQUESTED', status=status,
                        claim_token=None, claimed_by=None, lease_until=None)
        parent = parent.model_copy(update={'audit': (*original.audit, PrintAudit(action='REPRINT_REQUESTED', at=now, actor=user.subject, reason=reason))})
        ticket = original.ticket.model_copy(update={'receipt_text': 'REPRINT\n' + original.ticket.receipt_text})
        child = original.model_copy(update={'print_job_id': new_id, 'status': 'PENDING', 'created_at': now, 'updated_at': now,
                    'attempt_count': 0, 'printed_at': None, 'last_error': None, 'claim_token': None, 'claimed_by': None,
                    'lease_until': None, 'revision': str(uuid4()), 'ticket': ticket, 'reprint_of': original.print_job_id,
                    'reprint_reason': reason, 'requested_by': user.subject,
                    'audit': (PrintAudit(action='REPRINT_QUEUED', at=now, actor=user.subject, reason=reason),)})
        try: self.repository.save_reprint(original, parent, child)
        except PrintJobConflict:
            # Lost response / simultaneous same request: reconcile by deterministic child identity.
            try: existing = self.repository.get_print_job(user.business_id, new_id)
            except PrintJobNotFound: raise PrintJobConflict('Job changed. Refresh before requesting reprint.') from None
            if existing.requested_by != user.subject or existing.reprint_reason != reason: raise
            return job_view(existing, now, detailed=True)
        return job_view(child, now, detailed=True)
