from threading import RLock
from typing import Protocol
from .models import Customer


class DuplicatePhone(Exception):
    pass


class CustomerRepository(Protocol):
    def list(self, business_id: str) -> list[Customer]: ...
    def get(self, business_id: str, customer_id: str) -> Customer | None: ...
    def save(self, customer: Customer) -> None: ...


class InMemoryCustomerRepository:
    """Process-local storage. Uniqueness checks and writes are atomic."""
    def __init__(self):
        self._customers: dict[tuple[str, str], Customer] = {}
        self._lock = RLock()

    def list(self, business_id):
        with self._lock:
            return [c.model_copy(deep=True) for (business, _), c in self._customers.items() if business == business_id]

    def get(self, business_id, customer_id):
        with self._lock:
            customer = self._customers.get((business_id, customer_id))
            return customer.model_copy(deep=True) if customer else None

    def save(self, customer):
        with self._lock:
            if any(c.business_id == customer.business_id and c.phone == customer.phone and c.customer_id != customer.customer_id for c in self._customers.values()):
                raise DuplicatePhone()
            self._customers[(customer.business_id, customer.customer_id)] = customer.model_copy(deep=True)
