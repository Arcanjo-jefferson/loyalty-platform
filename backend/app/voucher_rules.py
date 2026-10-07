"""Pure reward policy. Calendar boundaries are Dublin midnights, never 24h TTLs."""
import calendar
import secrets
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4
from .models import Voucher
from .visit_dates import BUSINESS_TIMEZONE, local_visit_date

ZONE = ZoneInfo(BUSINESS_TIMEZONE)


def midnight_utc(day):
    return datetime.combine(day, time.min, ZONE).astimezone(timezone.utc)


def birthday_week(dob, today):
    # Adjacent years matter when a December/January birthday week crosses New Year.
    for year in (today.year - 1, today.year, today.year + 1):
        birthday = date(year, 3, 1) if dob.month == 2 and dob.day == 29 and not calendar.isleap(year) else date(year, dob.month, dob.day)
        start = birthday - timedelta(days=birthday.weekday())
        end = start + timedelta(days=7)
        if start <= today < end:
            return year, start, end
    return None


def voucher_code():
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # 32 symbols, no I/O/0/1.
    raw = ''.join(secrets.choice(alphabet) for _ in range(20))
    return '-'.join(raw[i:i + 5] for i in range(0, 20, 5))  # 100 bits.


def reward_key(voucher):
    cycle = voucher.loyalty_milestone if voucher.type == 'LOYALTY_10' else voucher.birthday_year
    return f'REWARD#{voucher.customer_id}#{voucher.type}#{cycle}'


def rewards_for_visit(customer, visit, total, reward_exists):
    today = local_visit_date(visit.visited_at)
    candidates = []
    if total > 0 and total % 5 == 0:
        candidates.append(('LOYALTY_10', 1000, None, total // 5, today + timedelta(days=1)))
    week = birthday_week(customer.date_of_birth, today)
    if week:
        year, _, end = week
        candidates.append(('BIRTHDAY_20', 2000, year, None, end))
    rewards = []
    for kind, cents, year, milestone, end in candidates:
        voucher = Voucher(business_id=visit.business_id, voucher_id=str(uuid4()), voucher_code=voucher_code(),
                          customer_id=visit.customer_id, type=kind, value_cents=cents, status='ACTIVE',
                          issued_at=visit.visited_at.astimezone(timezone.utc), issued_local_date=today,
                          timezone=BUSINESS_TIMEZONE, issued_by=visit.recorded_by,
                          qualifying_visit_id=visit.visit_id, birthday_year=year,
                          loyalty_milestone=milestone, expires_at=midnight_utc(end))
        if not reward_exists(visit.business_id, reward_key(voucher)):
            rewards.append(voucher)
    return rewards


def effective_voucher(voucher, now):
    if voucher.status == 'ACTIVE' and now >= voucher.expires_at:
        return voucher.model_copy(update={'status': 'EXPIRED'})
    return voucher
