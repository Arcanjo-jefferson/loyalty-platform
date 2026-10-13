"""Private durable queue models; no device secrets or printer transport."""
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TicketType = Literal['DAILY_RAFFLE', 'LOYALTY_10', 'BIRTHDAY_20']
PrintStatus = Literal['PENDING', 'CLAIMED', 'PRINTING', 'COMPLETED', 'RETRYABLE', 'FAILED', 'UNCERTAIN']


class PrintJobNotFound(Exception): pass
class PrintJobConflict(Exception): pass


class TicketSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    template_version: Literal[1, 2, 3] = 3
    business_name: str = Field(max_length=100)
    customer_name: str = Field(max_length=201)
    phone: str = Field(max_length=32)
    ticket_type: TicketType
    source_reference: str = Field(max_length=128)
    voucher_code: str | None = Field(default=None, max_length=100)
    issued_at: datetime
    expires_at: datetime | None = None
    receipt_text: str = Field(max_length=8000)
    receipt_columns: Literal[42] = 42
    timezone: Literal['Europe/Dublin'] = 'Europe/Dublin'

    @field_validator('issued_at', 'expires_at')
    @classmethod
    def utc_time(cls, value):
        if value is None: return None
        if value.tzinfo is None or value.utcoffset() is None: raise ValueError('Timezone required')
        return value.astimezone(timezone.utc)


class PrintAudit(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    action: str
    at: datetime
    actor: str
    reason: str | None = None


class PrintJob(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid')
    business_id: str
    print_job_id: str
    source_visit_id: str
    customer_id: str
    ticket_type: TicketType
    source_entry_id: str | None = None
    voucher_id: str | None = None
    status: PrintStatus = 'PENDING'
    created_at: datetime
    updated_at: datetime
    attempt_count: int = Field(default=0, ge=0, le=3)
    printed_at: datetime | None = None
    last_error: str | None = None
    claim_token: str | None = None
    claimed_by: str | None = None
    lease_until: datetime | None = None
    revision: str
    ticket: TicketSnapshot
    reprint_of: str | None = None
    reprint_reason: str | None = Field(default=None, max_length=300)
    requested_by: str
    audit: tuple[PrintAudit, ...] = ()

    @field_validator('created_at', 'updated_at', 'printed_at', 'lease_until')
    @classmethod
    def utc_time(cls, value):
        if value is None: return None
        if value.tzinfo is None or value.utcoffset() is None: raise ValueError('Timezone required')
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def consistent_job(self):
        base = f'{self.customer_id}.{self.source_visit_id}.{self.ticket_type}'
        if self.reprint_of:
            if self.reprint_of != base or not self.print_job_id.startswith(base + '.R'):
                raise ValueError('Invalid reprint/source identity')
        elif self.print_job_id != base:
            raise ValueError('Invalid source identity')
        if self.ticket.ticket_type != self.ticket_type:
            raise ValueError('Ticket type mismatch')
        reference = self.source_entry_id if self.ticket_type == 'DAILY_RAFFLE' else self.voucher_id
        if not reference or self.ticket.source_reference != reference:
            raise ValueError('Ticket source mismatch')
        if self.status in {'CLAIMED', 'PRINTING'}:
            if not self.claim_token or not self.claimed_by or not self.lease_until:
                raise ValueError('Claim fields required')
        elif self.claim_token or self.claimed_by or self.lease_until:
            raise ValueError('Terminal/pending job must not retain an active claim')
        if (self.status == 'COMPLETED') != (self.printed_at is not None):
            raise ValueError('Completion timestamp mismatch')
        return self
