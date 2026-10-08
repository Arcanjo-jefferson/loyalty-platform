from copy import deepcopy
from datetime import datetime
from threading import RLock
from typing import Protocol
from .models import Customer, Visit, Voucher, RaffleEntry
from .voucher_rules import effective_voucher, reward_key
from .visit_dates import normalize_visit, local_visit_date
from .raffle import raffle_for_visit
from .tickets import jobs_for_visit
from .print_models import PrintJobNotFound, PrintJobConflict, PrintJob


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
    def record_visit(self, visit: Visit, reward_factory=None) -> tuple[Customer, Visit, int, list[Voucher], RaffleEntry, list[PrintJob]]: ...
    def get_print_job(self, business_id: str, job_id: str) -> PrintJob: ...
    def print_jobs(self, business_id: str, customer_id=None, visit_id=None) -> list[PrintJob]: ...
    def save_print_change(self, previous: PrintJob, updated: PrintJob) -> None: ...
    def save_reprint(self, original: PrintJob, updated: PrintJob, job: PrintJob) -> None: ...
    def manage_qr(self, business_id: str, customer_id: str, *, expected_token: str | None = None): ...
    def public_qr_token(self, reference: str) -> str: ...
    def reward_exists(self, business_id: str, key: str) -> bool: ...
    def vouchers(self, business_id: str, customer_id: str) -> list[Voucher]: ...
    def get_voucher(self, business_id: str, customer_id: str, voucher_id: str) -> Voucher: ...
    def lookup_voucher(self, business_id: str, code: str) -> Voucher: ...
    def redeem_voucher(self, business_id: str, customer_id: str, voucher_id: str, now: datetime, subject: str) -> Voucher: ...
    def raffle_entries(self, business_id: str, customer_id: str) -> list[RaffleEntry]: ...
    def raffle_entries_for_date(self, business_id: str, raffle_date) -> list[RaffleEntry]: ...
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
        self._print_jobs = {}
        self._raffle_entries = {}
        self._vouchers = {}
        self._reward_locks = {}
        self._voucher_codes = {}
        self._public_qr = {}
        self._public_refs = {}

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

    def record_visit(self, visit, reward_factory=None):
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
            vouchers = []
            for attempt in range(3):
                vouchers = reward_factory(customer, saved, saved.visit_number, self.reward_exists) if reward_factory else []
                codes = [voucher.voucher_code for voucher in vouchers]
                if len(set(codes)) == len(codes) and not any((visit.business_id, code) in self._voucher_codes for code in codes):
                    break
            else: raise StorageUnavailable()
            entry = raffle_for_visit(saved)
            entry_key = (entry.business_id, entry.customer_id, entry.visit_id)
            if entry_key in self._raffle_entries: raise ConcurrentModification()
            jobs = jobs_for_visit(customer, saved, entry, vouchers)
            if any((job.business_id, job.print_job_id) in self._print_jobs for job in jobs): raise ConcurrentModification()
            for voucher in vouchers:
                self._vouchers[(voucher.business_id, voucher.customer_id, voucher.voucher_id)] = voucher.model_copy(deep=True)
                self._reward_locks[(voucher.business_id, reward_key(voucher))] = voucher.voucher_id
                self._voucher_codes[(voucher.business_id, voucher.voucher_code)] = (voucher.customer_id, voucher.voucher_id)
            self._visits[(visit.business_id, visit.visit_id)] = saved
            self._raffle_entries[entry_key] = entry
            for job in jobs: self._print_jobs[(job.business_id, job.print_job_id)] = job.model_copy(deep=True)
            return customer, saved, saved.visit_number, vouchers, entry, jobs

    def get_print_job(self, business_id, job_id):
        with self._lock:
            job = self._print_jobs.get((business_id, job_id))
            if not job: raise PrintJobNotFound()
            return job.model_copy(deep=True)

    def print_jobs(self, business_id, customer_id=None, visit_id=None):
        with self._lock:
            return sorted([job.model_copy(deep=True) for job in self._print_jobs.values()
                           if job.business_id == business_id and (not customer_id or job.customer_id == customer_id)
                           and (not visit_id or job.source_visit_id == visit_id)],
                          key=lambda job: (job.created_at, job.print_job_id), reverse=True)

    def save_print_change(self, previous, updated):
        with self._lock:
            current = self.get_print_job(previous.business_id, previous.print_job_id)
            if current.revision != previous.revision: raise PrintJobConflict('Job changed. Refresh before trying again.')
            self._print_jobs[(updated.business_id, updated.print_job_id)] = updated.model_copy(deep=True)

    def save_reprint(self, original, updated, job):
        with self._lock:
            current = self.get_print_job(original.business_id, original.print_job_id)
            if current.revision != original.revision or (job.business_id, job.print_job_id) in self._print_jobs:
                raise PrintJobConflict('Job changed. Refresh before trying again.')
            self._print_jobs[(updated.business_id, updated.print_job_id)] = updated.model_copy(deep=True)
            self._print_jobs[(job.business_id, job.print_job_id)] = job.model_copy(deep=True)

    def raffle_entries(self, business_id, customer_id):
        with self._lock:
            return sorted([entry.model_copy(deep=True) for entry in self._raffle_entries.values()
                           if entry.business_id == business_id and entry.customer_id == customer_id],
                          key=lambda entry: (entry.created_at, entry.raffle_entry_id), reverse=True)

    def raffle_entries_for_date(self, business_id, raffle_date):
        with self._lock:
            return sorted([entry.model_copy(deep=True) for entry in self._raffle_entries.values()
                           if entry.business_id == business_id and entry.raffle_date == raffle_date],
                          key=lambda entry: (entry.created_at, entry.raffle_entry_id), reverse=True)

    def reward_exists(self, business_id, key):
        with self._lock: return (business_id, key) in self._reward_locks

    def vouchers(self, business_id, customer_id):
        with self._lock:
            return sorted([v.model_copy(deep=True) for (business, owner, _), v in self._vouchers.items()
                           if business == business_id and owner == customer_id], key=lambda v: v.issued_at, reverse=True)

    def get_voucher(self, business_id, customer_id, voucher_id):
        from .voucher_repository import VoucherNotFound
        with self._lock:
            voucher = self._vouchers.get((business_id, customer_id, voucher_id))
            if voucher is None: raise VoucherNotFound()
            return voucher.model_copy(deep=True)

    def lookup_voucher(self, business_id, code):
        from .voucher_repository import VoucherNotFound
        with self._lock:
            owner = self._voucher_codes.get((business_id, code))
            if owner is None: raise VoucherNotFound()
            return self.get_voucher(business_id, *owner)

    def redeem_voucher(self, business_id, customer_id, voucher_id, now, subject):
        from .voucher_repository import VoucherNotRedeemable
        with self._lock:
            voucher = self.get_voucher(business_id, customer_id, voucher_id)
            if effective_voucher(voucher, now).status != 'ACTIVE': raise VoucherNotRedeemable()
            saved = voucher.model_copy(update={'status': 'REDEEMED', 'redeemed_at': now, 'redeemed_by': subject})
            self._vouchers[(business_id, customer_id, voucher_id)] = saved
            return saved.model_copy(deep=True)


    def manage_qr(self, business_id, customer_id, *, expected_token=None):
        import secrets
        from datetime import timezone
        from .qr_repository import QRNotFound
        with self._lock:
            customer = self.get(business_id, customer_id)
            if customer is None: raise QRNotFound()
            old_ref = self._public_refs.get((business_id, customer_id))
            if expected_token is not None and customer.qr_token != expected_token: raise ConcurrentModification()
            if expected_token is None and old_ref: return customer, old_ref
            reference = secrets.token_urlsafe(32)
            token = secrets.token_urlsafe(32) if expected_token is not None else customer.qr_token
            if reference in self._public_qr or ((business_id, token) in self._qr and token != customer.qr_token): raise ConcurrentModification()
            if expected_token is not None:
                self._qr.pop((business_id, customer.qr_token), None)
                customer = customer.model_copy(update={'qr_token': token, 'updated_at': datetime.now(timezone.utc)})
                self._customers[(business_id, customer_id)] = customer
            if old_ref: self._public_qr.pop(old_ref, None)
            self._qr[(business_id, token)] = customer_id
            self._public_refs[(business_id, customer_id)] = reference
            self._public_qr[reference] = (business_id, customer_id)
            return customer.model_copy(deep=True), reference

    def public_qr_token(self, reference):
        from .qr_repository import QRNotFound
        with self._lock:
            owner = self._public_qr.get(reference)
            customer = self.get(*owner) if owner else None
            if not customer or customer.status != 'active': raise QRNotFound()
            return customer.qr_token
