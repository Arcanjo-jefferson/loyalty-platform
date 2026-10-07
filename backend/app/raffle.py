"""Immutable PII-free raffle records, derived only from authoritative saved visits."""
from .models import RaffleEntry
from .visit_dates import normalize_visit


def raffle_for_visit(visit):
    visit = normalize_visit(visit)
    # The random visit UUID is also the entry UUID: one deterministic entry per visit.
    return RaffleEntry(business_id=visit.business_id, raffle_entry_id=visit.visit_id,
                       customer_id=visit.customer_id, visit_id=visit.visit_id,
                       raffle_date=visit.local_visit_date, created_at=visit.visited_at,
                       recorded_by=visit.recorded_by, visit_number=visit.visit_number,
                       business_timezone=visit.business_timezone)


def raffle_key(entry):
    return f'RAFFLE#{entry.customer_id}#{entry.visit_id}'


def raffle_date_key(entry):
    return f'RAFFLE_DATE#{entry.raffle_date.isoformat()}#{entry.customer_id}#{entry.visit_id}'


class RaffleService:
    def __init__(self, customers):
        self.customers, self.repository = customers, customers.repository

    def history(self, business_id, customer_id):
        self.customers.get(business_id, customer_id)
        return self.repository.raffle_entries(business_id, customer_id)

    def for_date(self, business_id, raffle_date):
        """Internal reporting boundary; no reporting/draw/public endpoint in 5C."""
        return self.repository.raffle_entries_for_date(business_id, raffle_date)
