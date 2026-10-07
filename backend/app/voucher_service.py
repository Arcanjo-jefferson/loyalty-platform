"""Authenticated voucher reads/redemption; arbitrary issuance is not exposed."""
import re
from datetime import datetime, timezone
from .voucher_rules import effective_voucher
from .voucher_repository import VoucherNotFound


def normalize_code(value):
    compact = re.sub(r'[\s-]', '', value).upper()
    if not re.fullmatch(r'[A-HJ-NP-Z2-9]{20}', compact): raise VoucherNotFound()
    return '-'.join(compact[i:i + 5] for i in range(0, 20, 5))


class VoucherService:
    def __init__(self, customers, clock=None):
        self.customers, self.repository = customers, customers.repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def list(self, business_id, customer_id):
        self.customers.get(business_id, customer_id)
        now = self.clock().astimezone(timezone.utc)
        return [effective_voucher(v, now) for v in self.repository.vouchers(business_id, customer_id)]

    def lookup(self, business_id, code):
        voucher = self.repository.lookup_voucher(business_id, normalize_code(code))
        return effective_voucher(voucher, self.clock().astimezone(timezone.utc))

    def redeem(self, user, customer_id, voucher_id):
        return self.repository.redeem_voucher(user.business_id, customer_id, voucher_id,
                                              self.clock().astimezone(timezone.utc), user.subject)
