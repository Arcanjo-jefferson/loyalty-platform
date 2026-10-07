"""Scan identifies a customer; only explicit confirmation records a visit."""
from datetime import datetime, timezone
from uuid import uuid4
from .models import Visit
from .voucher_rules import rewards_for_visit
from .repository import InactiveCustomer
from .service import CustomerNotFound

REWARD_THRESHOLD = 5


def loyalty_progress(total):
    return {'total_visits': total, 'progress': total % REWARD_THRESHOLD,
            'visits_until_reward': REWARD_THRESHOLD - total % REWARD_THRESHOLD,
            'reward_earned': total > 0 and total % REWARD_THRESHOLD == 0}


class LoyaltyService:
    def __init__(self, customers, clock=None):
        self.customers, self.repository = customers, customers.repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def lookup(self, business_id, qr_token):
        customer = self.repository.find_active_by_qr(business_id, qr_token)
        if customer is None: raise CustomerNotFound()
        return {'customer': customer, **loyalty_progress(self.repository.total_visits(business_id, customer.customer_id))}

    def confirm(self, user, customer_id):
        customer = self.customers.get(user.business_id, customer_id)
        if customer.status != 'active': raise InactiveCustomer()
        visit = Visit(business_id=user.business_id, visit_id=str(uuid4()), customer_id=customer_id,
                      visited_at=self.clock(), recorded_by=user.subject)
        saved_customer, saved_visit, count, vouchers, raffle_entry = self.repository.record_visit(visit, rewards_for_visit)
        return {'customer': saved_customer, 'visit': saved_visit, 'vouchers': vouchers, 'raffle_entry': raffle_entry, **loyalty_progress(count)}

    def history(self, business_id, customer_id):
        customer = self.customers.get(business_id, customer_id)
        history = self.repository.visits(business_id, customer_id)
        return {'customer': customer, 'visits': history,
                **loyalty_progress(self.repository.total_visits(business_id, customer_id))}
