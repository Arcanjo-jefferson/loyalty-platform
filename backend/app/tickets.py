"""Versioned, immutable 42-column monochrome ticket text generated locally."""
import re
import textwrap
from uuid import uuid4
from zoneinfo import ZoneInfo
from .print_models import PrintJob, TicketSnapshot, PrintAudit


def clean_text(value):
    # Strip control characters (including ESC/POS commands), normalize whitespace.
    return re.sub(r'\s+', ' ', ''.join(char if char.isprintable() else ' ' if char.isspace() else '' for char in value)).strip()


def local_time(value):
    return value.astimezone(ZoneInfo('Europe/Dublin')).strftime('%d/%m/%Y %H:%M %Z')


def print_job_id(customer_id, visit_id, ticket_type):
    return f'{customer_id}.{visit_id}.{ticket_type}'


def ticket_snapshot(customer, visit, entry, voucher=None):
    kind = voucher.type if voucher else 'DAILY_RAFFLE'
    business = 'Trumps' if customer.business_id == 'trumps' else 'Contactly'
    name = clean_text(f'{customer.first_name} {customer.last_name}')
    reference = voucher.voucher_id if voucher else entry.raffle_entry_id
    issued = voucher.issued_at if voucher else entry.created_at
    lines = [business, 'BIRTHDAY VOUCHER' if kind == 'BIRTHDAY_20' else 'LOYALTY BONUS', '', name, customer.phone, '']
    if voucher:
        lines += ['€10 Loyalty Voucher' if kind == 'LOYALTY_10' else '€20 Birthday Voucher',
                  'Voucher code:', voucher.voucher_code, 'Issued: ' + local_time(issued),
                  'Valid until (exclusive): ' + local_time(voucher.expires_at)]
    else:
        lines += ['You have just entered our Daily Raffle!', 'Please sign and place in Raffle Drum.', 'GOOD LUCK!',
                  'Visit/raffle: ' + reference, 'Date/time: ' + local_time(issued)]
    lines += ['', 'Customer signature:', '_______________________________', '', 'Europe/Dublin']
    receipt = '\n'.join('\n'.join(textwrap.wrap(line, width=42)) if line else '' for line in lines)
    return TicketSnapshot(business_name=business, customer_name=name, phone=customer.phone, ticket_type=kind,
                          source_reference=reference, voucher_code=voucher.voucher_code if voucher else None,
                          issued_at=issued, expires_at=voucher.expires_at if voucher else None, receipt_text=receipt)


def jobs_for_visit(customer, visit, entry, vouchers):
    jobs = []
    for voucher in [None, *vouchers]:
        ticket = ticket_snapshot(customer, visit, entry, voucher)
        jobs.append(PrintJob(business_id=customer.business_id,
            print_job_id=print_job_id(customer.customer_id, visit.visit_id, ticket.ticket_type),
            source_visit_id=visit.visit_id, customer_id=customer.customer_id, ticket_type=ticket.ticket_type,
            source_entry_id=entry.raffle_entry_id if voucher is None else None,
            voucher_id=voucher.voucher_id if voucher else None, created_at=visit.visited_at, updated_at=visit.visited_at,
            revision=str(uuid4()), ticket=ticket, requested_by=visit.recorded_by,
            audit=(PrintAudit(action='QUEUED', at=visit.visited_at, actor=visit.recorded_by),)))
    return jobs
