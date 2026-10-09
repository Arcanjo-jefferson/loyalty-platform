"""Validate and preserve server-authored immutable receipt text, never clock time."""
from datetime import datetime
from zoneinfo import ZoneInfo


def receipt_text(job):
    ticket=job['ticket']
    text=ticket['receipt_text']
    # Legacy snapshots remain byte-for-byte unchanged, including their original
    # minute-resolution timestamps. Versions 2/3 use explicit labels; version 3 includes actual minutes.
    if ticket.get('template_version',1) in {2,3}:
        issued=datetime.fromisoformat(ticket['issued_at'])
        if issued.tzinfo is None or issued.utcoffset() is None:
            raise ValueError('An aware original issuance timestamp is required.')
        if ticket.get('timezone')!='Europe/Dublin': raise ValueError('Unsupported business timezone.')
        local=issued.astimezone(ZoneInfo('Europe/Dublin'))
        expected=['Issued date: '+local.strftime('%d/%m/%Y'),'Issued time: '+local.strftime('%H:%M' if ticket['template_version']==3 else '%H')]
        if not all(line in text.splitlines() for line in expected):
            raise ValueError('Receipt issuance display does not match the immutable timestamp.')
        if job.get('reprint_of') and not text.startswith('REPRINT\n'):
            raise ValueError('Explicit reprint must retain its REPRINT label.')
    return text
