from datetime import datetime
from threading import RLock
from typing import Protocol
from .models import Customer


class DuplicatePhone(Exception):
    pass


class StorageUnavailable(Exception):
    pass


class ConcurrentModification(Exception):
    pass


class CustomerRepository(Protocol):
    def list(self, business_id: str) -> list[Customer]: ...
    def get(self, business_id: str, customer_id: str) -> Customer | None: ...
    def save(self, customer: Customer, *, expected_updated_at: datetime | None = None) -> None:
        """Create when no expected timestamp is supplied; otherwise conditionally update."""
        ...


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

    def save(self, customer, *, expected_updated_at=None):
        with self._lock:
            existing = self._customers.get((customer.business_id, customer.customer_id))
            if expected_updated_at is None:
                if existing is not None:
                    raise ConcurrentModification()
            elif existing is None or existing.updated_at != expected_updated_at:
                raise ConcurrentModification()
            if any(c.business_id == customer.business_id and c.phone == customer.phone and c.customer_id != customer.customer_id for c in self._customers.values()):
                raise DuplicatePhone()
            self._customers[(customer.business_id, customer.customer_id)] = customer.model_copy(deep=True)
