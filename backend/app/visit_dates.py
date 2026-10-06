"""Server-owned business calendar policy; never supplied by an API caller."""
from datetime import timezone
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = 'Europe/Dublin'


def local_visit_date(timestamp):
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError('Visit timestamp must include a timezone.')
    return timestamp.astimezone(ZoneInfo(BUSINESS_TIMEZONE)).date()


def normalize_visit(visit):
    return visit.model_copy(update={
        'visited_at': visit.visited_at.astimezone(timezone.utc),
        'local_visit_date': local_visit_date(visit.visited_at),
        'business_timezone': BUSINESS_TIMEZONE,
    })
