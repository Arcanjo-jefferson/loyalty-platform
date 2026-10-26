"""Provider-neutral contracts. Events are internal, not authenticated webhook inputs.
A future adapter MUST authenticate the original request and bind its provider
account before returning events. No caller-supplied business ID authorizes events.
"""
from typing import Literal, Mapping, Protocol
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

ProviderName = Literal['simulation', 'twilio', 'clicksend']


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class SendRequest(Contract):
    sender: str = Field(min_length=1)
    destination: str = Field(min_length=1, repr=False)
    body: str = Field(min_length=1, max_length=1600, repr=False)
    message_id: str = Field(min_length=1)  # Stable application idempotency key.


class Delivery(Contract):
    status: Literal['SIMULATED', 'ACCEPTED', 'SENT', 'DELIVERED', 'UNDELIVERED', 'FAILED', 'UNKNOWN']
    provider_id: str = Field(min_length=1)


class DeliveryStatusEvent(Contract):
    provider: ProviderName
    account_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=256)
    provider_message_id: str = Field(min_length=1, max_length=256)
    occurred_at: AwareDatetime
    status: Literal['ACCEPTED', 'SENT', 'DELIVERED', 'UNDELIVERED', 'FAILED', 'UNKNOWN']
    destination: str | None = Field(default=None, max_length=32, repr=False)
    error_code: str | None = Field(default=None, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')  # Normalized code, never raw provider exception text.


class IncomingSTOPEvent(Contract):
    provider: ProviderName
    account_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=256)
    occurred_at: AwareDatetime
    sender: str = Field(min_length=1, repr=False)
    destination: str = Field(min_length=1, repr=False)
    keyword: Literal['STOP'] = 'STOP'


class IncomingSMSEvent(Contract):
    """Returned only after a provider adapter authenticates the original request."""
    provider: ProviderName
    account_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=256)
    occurred_at: AwareDatetime
    sender: str = Field(min_length=1, max_length=32, repr=False)
    destination: str = Field(min_length=1, max_length=32, repr=False)
    body: str = Field(max_length=1600, repr=False)


class SafeRetry(Exception):
    """Guaranteed not submitted. Only this category permits bounded retry."""


class PermanentProviderError(Exception):
    """Known rejection, guaranteed not accepted. Do not retry."""


class UncertainProviderError(Exception):
    """Submission may have happened. Never automatically resend/fail over."""


class ProviderUnavailable(RuntimeError):
    """Disabled/unimplemented or invalid configuration; no submission occurred."""


class SMSProvider(Protocol):
    def send(self, request: SendRequest) -> Delivery: ...


class ProviderEventAdapter(Protocol):
    def verify_incoming(self, *, body: bytes, headers: Mapping[str, str], url: str) -> IncomingSMSEvent: ...
    def verify_delivery(self, *, body: bytes, headers: Mapping[str, str], url: str) -> DeliveryStatusEvent: ...
    def verify_stop(self, *, body: bytes, headers: Mapping[str, str], url: str) -> IncomingSTOPEvent: ...


class SMSEventProcessor(Protocol):
    """Trusted correlation/dedup boundary, implemented by SMSEvents.receive.
    Resolve tenant from verified account/message binding; deduplicate events;
    enforce status transitions; STOP writes durable phone suppression even when
    no active customer exists. No automatic resend or re-consent on an event.
    """
    def receive(self, kind: str, provider: str, *, body: bytes,
                headers: Mapping[str, str], url: str) -> dict: ...
