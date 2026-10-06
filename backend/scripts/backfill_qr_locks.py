"""Explicit, tenant-scoped QR migration. Dry-run by default; never table Scan."""
import argparse
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings, build_repository
from app.dynamodb_repository import DynamoDBCustomerRepository
from app.repository import DuplicateQR, ConcurrentModification, StorageUnavailable


def backfill(repository, business_id, apply=False):
    customers = repository.list(business_id)  # Strongly consistent paginated Query.
    seen = set()
    missing = 0
    for customer in customers:
        if not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', customer.qr_token):
            raise ValueError('Invalid existing QR token. No tokens were changed.')
        if customer.qr_token in seen: raise DuplicateQR()
        seen.add(customer.qr_token)
        lock = repository._read_item(business_id, 'QR#' + customer.qr_token)
        if lock is None: missing += 1
        elif lock.get('item_type') != 'QR_LOCK' or lock.get('owner_customer_id') != customer.customer_id:
            raise DuplicateQR()
    # Preflight every candidate before any write. Every write is also guarded
    # against a conflicting owner or concurrent token/customer changes.
    if apply:
        for customer in customers: repository.ensure_qr_lock(customer)
    return {'customers': len(customers), 'missing': missing, 'applied': apply}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--business', required=True)
    parser.add_argument('--apply', action='store_true', help='Write QR locks after preflight; default only reports counts.')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.business): parser.error('Invalid business identifier.')
    try:
        settings = Settings.from_environment()
        if settings.customer_repository != 'dynamodb': raise ValueError('Select CUSTOMER_REPOSITORY=dynamodb for this migration.')
        repository = build_repository(settings)
        if not isinstance(repository, DynamoDBCustomerRepository): raise ValueError('A DynamoDB repository is required.')
        result = backfill(repository, args.business, args.apply)
        print(f"Customers: {result['customers']}; missing QR locks: {result['missing']}; mode: {'APPLY' if args.apply else 'DRY RUN'}")
    except DuplicateQR:
        print('QR collision or conflicting lock detected. Resolve manually; no tokens were changed.', file=sys.stderr); return 1
    except ConcurrentModification:
        print('A customer changed during backfill. Review and rerun; existing tokens remain unchanged.', file=sys.stderr); return 1
    except (StorageUnavailable, ValueError) as error:
        print(str(error) if isinstance(error, ValueError) else 'Backfill storage access failed. Check local AWS configuration.', file=sys.stderr); return 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
