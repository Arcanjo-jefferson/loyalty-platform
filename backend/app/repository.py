from copy import deepcopy
from datetime import datetime
from threading import RLock
from typing import Protocol
from .models import Customer, Visit
from .visit_dates import normalize_visit, local_visit_date


class DuplicatePhone(Exception):
    pass


class StorageUnavailable(Exception):
    pass


class ConcurrentModification(Exception):
    pass


class DuplicateQR(Exception):
    pass


class DuplicateVisit(Exception):
    pass


class InactiveCustomer(Exception):
    pass


class CustomerRepository(Protocol):
    def find_active_by_qr(self, business_id: str, qr_token: str) -> Customer | None: ...
    def record_visit(self, visit: Visit) -> tuple[Customer, Visit, int]: ...
    def visits(self, business_id: str, customer_id: str) -> list[Visit]: ...
    def total_visits(self, business_id: str, customer_id: str) -> int: ...
    def get_media(self, business_id: str, customer_id: str, kind: str) -> dict | None: ...
    def save_media(self, business_id: str, customer_id: str, kind: str, metadata: dict, *, expected_revision: str | None) -> None: ...

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
        self._media = {}
        self._qr = {}
        self._visits = {}

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
            owner = self._qr.get((customer.business_id, customer.qr_token))
            if owner is not None and owner != customer.customer_id:
                raise DuplicateQR()
            if existing and existing.qr_token != customer.qr_token:
                raise ConcurrentModification()
            self._qr[(customer.business_id, customer.qr_token)] = customer.customer_id
            self._customers[(customer.business_id, customer.customer_id)] = customer.model_copy(deep=True)

    def get_media(self, business_id, customer_id, kind):
        with self._lock:
            return deepcopy(self._media.get((business_id, customer_id, kind)))

    def save_media(self, business_id, customer_id, kind, metadata, *, expected_revision):
        with self._lock:
            current = self._media.get((business_id, customer_id, kind))
            if (business_id, customer_id) not in self._customers or (current or {}).get('revision') != expected_revision:
                raise ConcurrentModification()
            self._media[(business_id, customer_id, kind)] = deepcopy(metadata)

    def find_active_by_qr(self, business_id, qr_token):
        with self._lock:
            owner = self._qr.get((business_id, qr_token))
            customer = self.get(business_id, owner) if owner else None
            return customer if customer and customer.status == 'active' else None

    def visits(self, business_id, customer_id):
        with self._lock:
            return sorted([v.model_copy(deep=True) for v in self._visits.values()
                           if v.business_id == business_id and v.customer_id == customer_id],
                          key=lambda v: v.visit_number)

    def total_visits(self, business_id, customer_id):
        return len(self.visits(business_id, customer_id))

    def record_visit(self, visit):
        visit = normalize_visit(visit)
        with self._lock:
            customer = self.get(visit.business_id, visit.customer_id)
            if customer is None: raise ConcurrentModification()
            if customer.status != 'active': raise InactiveCustomer()
            history = self.visits(visit.business_id, visit.customer_id)
            if any(local_visit_date(previous.visited_at) == visit.local_visit_date for previous in history):
                raise DuplicateVisit()
            saved = visit.model_copy(update={'visit_number': len(history) + 1})
            if (visit.business_id, visit.visit_id) in self._visits: raise ConcurrentModification()
            self._visits[(visit.business_id, visit.visit_id)] = saved
            return customer, saved, saved.visit_number
