from datetime import datetime, timezone
from secrets import token_urlsafe
from uuid import uuid4
from .models import Customer, CustomerInput
from .repository import CustomerRepository


class CustomerNotFound(Exception):
    pass


class CustomerService:
    def __init__(self, repository: CustomerRepository):
        self.repository = repository

    def list(self, business_id):
        return self.repository.list(business_id)

    def get(self, business_id, customer_id):
        customer = self.repository.get(business_id, customer_id)
        if customer is None:
            raise CustomerNotFound()
        return customer

    def create(self, business_id: str, data: CustomerInput):
        now = datetime.now(timezone.utc)
        customer = Customer(**data.model_dump(), business_id=business_id, customer_id=str(uuid4()), qr_token=token_urlsafe(32), consent_timestamp=now if data.marketing_consent else None, created_at=now, updated_at=now)
        self.repository.save(customer)
        return customer

    def update(self, business_id: str, customer_id: str, data: CustomerInput):
        old = self.get(business_id, customer_id)
        now = datetime.now(timezone.utc)
        consent_time = old.consent_timestamp
        if old.marketing_consent != data.marketing_consent:
            consent_time = now
        customer = old.model_copy(update={**data.model_dump(), 'consent_timestamp': consent_time, 'updated_at': now})
        self.repository.save(customer)
        return customer
