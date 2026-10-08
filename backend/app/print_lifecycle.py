"""Fenced claim/start/ack states. Started output is never automatically retried."""
import secrets
from datetime import timedelta
from uuid import uuid4
from .print_models import PrintJobConflict, PrintAudit

LEASE_SECONDS = 120
MAX_ATTEMPTS = 3


def effective_status(job, now):
    if job.status in {'CLAIMED', 'PRINTING'} and job.lease_until and job.lease_until <= now:
        if job.status == 'PRINTING': return 'UNCERTAIN'
        return 'RETRYABLE' if job.attempt_count < MAX_ATTEMPTS else 'FAILED'
    return job.status


def change(job, now, actor, action, **updates):
    return job.model_copy(update={**updates, 'updated_at': now, 'revision': str(uuid4()),
        'audit': (*job.audit, PrintAudit(action=action, at=now, actor=actor, reason=updates.get('last_error')))})


def transition(job, action, now, actor, token=None):
    status = effective_status(job, now)
    if action == 'review':
        if status == job.status: raise PrintJobConflict('This job has no expired lease to review.')
        return change(job, now, actor, 'LEASE_EXPIRED', status=status,
                      claim_token=None, claimed_by=None, lease_until=None,
                      last_error='PRINT_OUTCOME_UNKNOWN' if status == 'UNCERTAIN' else 'CLAIM_EXPIRED_BEFORE_START')
    if action == 'claim':
        if status not in {'PENDING', 'RETRYABLE'} or job.attempt_count >= MAX_ATTEMPTS:
            raise PrintJobConflict('Job cannot be claimed. Uncertain output requires explicit operator reprint.')
        return change(job, now, actor, 'CLAIMED', status='CLAIMED', attempt_count=job.attempt_count + 1,
                      claim_token=secrets.token_urlsafe(32), claimed_by=actor,
                      lease_until=now + timedelta(seconds=LEASE_SECONDS), last_error=None)
    # All output-affecting acknowledgements require the current unexpired fence AND owner.
    if (not token or not job.claim_token or not secrets.compare_digest(token, job.claim_token)
            or job.claimed_by != actor or not job.lease_until or job.lease_until <= now):
        raise PrintJobConflict('Claim is invalid or expired. Refresh job status; do not print again automatically.')
    if action == 'renew' and job.status in {'CLAIMED', 'PRINTING'}:
        return change(job, now, actor, 'LEASE_RENEWED', lease_until=now + timedelta(seconds=LEASE_SECONDS))
    if action == 'submitted' and job.status == 'PRINTING':
        # Spooler submission is evidence of acceptance, not physical paper output.
        return change(job, now, actor, 'SPOOL_SUBMITTED', status='UNCERTAIN',
                      claim_token=None, claimed_by=None, lease_until=None,
                      last_error='SPOOL_ACCEPTED_PHYSICAL_OUTPUT_UNCONFIRMED')
    if action == 'start' and job.status == 'CLAIMED':
        return change(job, now, actor, 'PRINTING', status='PRINTING')
    if action == 'complete' and job.status == 'PRINTING':
        return change(job, now, actor, 'COMPLETED', status='COMPLETED', printed_at=now,
                      claim_token=None, claimed_by=None, lease_until=None, last_error=None)
    if action == 'fail' and job.status in {'CLAIMED', 'PRINTING'}:
        uncertain = job.status == 'PRINTING'
        return change(job, now, actor, 'FAILED_ATTEMPT',
                      status='UNCERTAIN' if uncertain else 'RETRYABLE' if job.attempt_count < MAX_ATTEMPTS else 'FAILED',
                      claim_token=None, claimed_by=None, lease_until=None,
                      last_error='PRINT_OUTCOME_UNKNOWN' if uncertain else 'PREPRINT_FAILURE')
    raise PrintJobConflict('Invalid print-job state transition.')
