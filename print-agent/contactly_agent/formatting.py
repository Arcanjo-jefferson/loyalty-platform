"""Validate and preserve server-authored immutable receipt text, never clock time."""
from datetime import datetime
from zoneinfo import ZoneInfo


def receipt_text(job):
    ticket=job['ticket']
    text=ticket['receipt_text']
    # Legacy snapshots remain byte-for-byte unchanged, including their original
    # minute-resolution timestamps. Versions 2–4 use explicit labels; versions 3/4 include actual minutes.
    if ticket.get('template_version',1) in {2,3,4}:
        issued=datetime.fromisoformat(ticket['issued_at'])
        if issued.tzinfo is None or issued.utcoffset() is None:
            raise ValueError('An aware original issuance timestamp is required.')
        if ticket.get('timezone')!='Europe/Dublin': raise ValueError('Unsupported business timezone.')
        local=issued.astimezone(ZoneInfo('Europe/Dublin'))
        expected=['Issued date: '+local.strftime('%d/%m/%Y'),'Issued time: '+local.strftime('%H:%M' if ticket['template_version']>=3 else '%H')]
        if not all(line in [part.strip() for part in text.splitlines()] for line in expected):
            raise ValueError('Receipt issuance display does not match the immutable timestamp.')
        if job.get('reprint_of') and text.splitlines()[0].strip() != 'REPRINT':
            raise ValueError('Explicit reprint must retain its REPRINT label.')
    return text


def thermal_content(job, text):
    """Design-only emphasis: double height preserves the existing 42-column width."""
    if job['ticket'].get('template_version', 1) < 4:
        return text.encode('cp858')
    amounts = {'€10 LOYALTY VOUCHER', '€20 BIRTHDAY VOUCHER'}
    return b'\n'.join(
        b'\x1b!\x10' + line.encode('cp858') + b'\x1b!\x00'
        if line.strip() in amounts else line.encode('cp858')
        for line in text.split('\n'))
