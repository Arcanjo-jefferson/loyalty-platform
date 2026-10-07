import re
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, Field, field_validator


class CustomerInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str
    date_of_birth: date
    email: str | None = Field(default=None, max_length=254)
    address: str | None = Field(default=None, max_length=500)
    eircode: str | None = Field(default=None, max_length=10)
    marketing_consent: bool = False
    status: Literal['active', 'inactive'] = 'active'

    @field_validator('phone')
    @classmethod
    def normalize_phone(cls, value):
        # Accept human formatting, but never discard letters or arbitrary punctuation.
        value = re.sub(r'[ ().-]', '', value)
        if re.fullmatch(r'08[35679][0-9]{7}', value):
            return '+353' + value[1:]
        if re.fullmatch(r'\+3538[35679][0-9]{7}', value):
            return value
        raise ValueError('Enter a valid Irish mobile number, e.g. 0871234567 or +353871234567.')

    @field_validator('email', 'address', 'eircode', mode='before')
    @classmethod
    def empty_to_none(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @field_validator('email')
    @classmethod
    def validate_email(cls, value):
        if value and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter a valid email address')
        return value

    @field_validator('date_of_birth')
    @classmethod
    def validate_birth_date(cls, value):
        today = datetime.now(ZoneInfo('Europe/Dublin')).date()
        if value > today:
            raise ValueError('Date of birth cannot be in the future.')
        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age < 18:
            raise ValueError('Customer must be at least 18 years old.')
        return value


class Customer(CustomerInput):
    business_id: str
    customer_id: str
    consent_timestamp: datetime | None
    qr_token: str
    created_at: datetime
    updated_at: datetime


class Visit(BaseModel):
    business_id: str
    visit_id: str
    customer_id: str
    visited_at: datetime
    recorded_by: str
    visit_number: int = Field(default=0, ge=0)
    local_visit_date: date | None = None
    business_timezone: str | None = None


class Voucher(BaseModel):
    business_id: str
    voucher_id: str
    voucher_code: str
    customer_id: str
    type: Literal['LOYALTY_10', 'BIRTHDAY_20']
    value_cents: int = Field(gt=0)
    status: Literal['ACTIVE', 'REDEEMED', 'EXPIRED']
    issued_at: datetime
    issued_local_date: date
    timezone: str
    issued_by: str
    qualifying_visit_id: str
    birthday_year: int | None = None
    loyalty_milestone: int | None = None
    expires_at: datetime
    redeemed_at: datetime | None = None
    redeemed_by: str | None = None
