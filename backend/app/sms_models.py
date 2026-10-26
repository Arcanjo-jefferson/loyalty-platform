"""Simulation-only SMS contracts and segment estimates; money is integer EUR micros."""
import math
import os
import json
import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .sms_provider import provider_identity

GSM = set('@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !"#¤%&\'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà')
EXT = set('\f^{}\\[~]|€')


def estimate(text):
    if all(c in GSM or c in EXT for c in text):
        units = sum(2 if c in EXT else 1 for c in text)
        encoding, single, multi = 'GSM-7', 160, 153
    else:
        units = len(text.encode('utf-16-be')) // 2
        encoding, single, multi = 'UCS-2', 70, 67
    return {'characters': len(text), 'units': units, 'encoding': encoding,
            'segments': 0 if not units else 1 if units <= single else math.ceil(units / multi)}


def render(template, first_name):
    # Only a literal first-name placeholder: no format/eval, attributes or cross-recipient data.
    name = re.sub(r'\s+', ' ', ''.join(c for c in first_name if c.isprintable())).strip()[:100] or 'customer'
    return template.replace('{first_name}', name)


class Compose(BaseModel):
    model_config = ConfigDict(extra='forbid')
    audience: Literal['individual', 'all']
    customer_id: UUID | None = None
    message: str = Field(min_length=1, max_length=1600)

    @model_validator(mode='after')
    def validate_message(self):
        if (self.audience == 'individual') != (self.customer_id is not None):
            raise ValueError('Select one customer for individual messaging.')
        remaining = self.message.replace('{first_name}', '')
        if not self.message.strip() or '{' in remaining or '}' in remaining:
            raise ValueError('Only {first_name} personalisation is supported.')
        if any(ord(c) < 32 and c not in '\n\r\t' for c in self.message):
            raise ValueError('Message contains unsupported control characters.')
        # Refuse unpaired surrogates rather than failing during encoding/storage.
        self.message.encode('utf-16-be')
        return self


class Confirm(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmed: bool


@dataclass(frozen=True)
class SMSSettings:
    sender: str = 'Loyalty System (simulation)'
    segment_price_micros: int = 100000  # Illustrative EUR 0.10; NOT a Twilio tariff.
    monthly_limit_micros: int = 20000000
    provider: str = 'simulation'

    def __post_init__(self):
        if (self.provider not in {'simulation', 'twilio', 'clicksend'} or not isinstance(self.sender, str) or not self.sender.strip() or len(self.sender) > 80
                or type(self.segment_price_micros) is not int or self.segment_price_micros <= 0
                or type(self.monthly_limit_micros) is not int or self.monthly_limit_micros < 0):
            raise ValueError('Invalid SMS provider or integer EUR limits.')

    @classmethod
    def for_business(cls, business):
        config = json.loads(os.getenv('SMS_BUSINESS_SETTINGS_JSON', '{}'))
        if not isinstance(config, dict): raise ValueError('Invalid SMS business settings.')
        selected = config.get(business, {})
        if not isinstance(selected, dict): raise ValueError('Invalid SMS business settings.')
        selected = dict(selected)
        selected.setdefault('provider', os.getenv('SMS_PROVIDER', 'simulation'))
        provider_identity(selected['provider'])
        return cls(**selected)


class SMSRecipientHistory(BaseModel):
    """Delivery/history projection; simulation never emits a real delivery claim."""
    model_config = ConfigDict(extra='forbid')
    id: str
    name: str
    phone: str
    status: Literal['DRAFT', 'QUEUED', 'SUBMITTING', 'RETRYABLE', 'SIMULATED', 'SUPPRESSED', 'FAILED', 'UNKNOWN']
    updated_at: str
    provider_id: str | None = None
    reason: str | None = None
    consent_timestamp: str
    consent_decision: str
    body: str
    characters: int
    units: int
    encoding: Literal['GSM-7', 'UCS-2']
    segments: int
