"""DEVELOPMENT/ACCEPTANCE TEST DATA ONLY. Never expose as an application endpoint.

For one explicitly selected, active fictional customer with zero history/rewards,
atomically insert four synthetic prior-day visits without evaluating reward rules.
Dry-run by default. --verify is read-only and verifies the four-visit seed before
normal API visit #5. Uses existing backend environment/profile; creates no AWS
resources. recorded_by deliberately identifies synthetic tooling, not a Cognito
user. Run only against a development table with a fictional customer.
"""
import argparse
import json
import re
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from botocore.exceptions import BotoCoreError, ClientError
from app.config import Settings, build_repository
from app.dynamodb_repository import DynamoDBCustomerRepository
from app.models import Visit
from app.repository import StorageUnavailable
from app.visit_dates import BUSINESS_TIMEZONE, normalize_visit, local_visit_date
from app.loyalty_service import loyalty_progress

RECORDED_BY = 'development:milestone-5b-acceptance-seed'


def reward_locks(repository, business_id, customer_id):
    params = {'TableName': repository.table_name,
              'KeyConditionExpression': '#business = :business AND begins_with(#sk, :prefix)',
              'ExpressionAttributeNames': {'#business': 'business_id', '#sk': 'customer_id'},
              'ExpressionAttributeValues': repository._encode({':business': business_id, ':prefix': f'REWARD#{customer_id}#'}),
              'ConsistentRead': True}
    while True:
        page = repository._call('query', **params)
        if page.get('Items'): return True
        if not page.get('LastEvaluatedKey'): return False
        params['ExclusiveStartKey'] = page['LastEvaluatedKey']


def snapshot(repository, business_id, customer_id):
    if not isinstance(repository, DynamoDBCustomerRepository): raise ValueError('A DynamoDB repository is required.')
    # Read the counter before range checks; its transaction condition protects
    # against concurrent normal visits/rewards. There is no DynamoDB range lock.
    customer = repository.get(business_id, customer_id)
    if customer is None or customer.business_id != business_id: raise ValueError('Customer not found in the supplied business.')
    if customer.status != 'active': raise ValueError('Customer must be active.')
    item, count = repository._visit_state(business_id, customer_id)
    if item.get('status') != 'active': raise ValueError('Customer must be active.')
    history = repository.visits(business_id, customer_id)
    vouchers = repository.vouchers(business_id, customer_id)
    locks = reward_locks(repository, business_id, customer_id)
    return customer, item, count, history, vouchers, locks


def seed(repository, business_id, customer_id, *, apply=False, now=None):
    customer, item, count, history, vouchers, locks = snapshot(repository, business_id, customer_id)
    if count != 0 or history: raise ValueError('Refusing: customer already has visits or a nonzero counter.')
    if vouchers or locks: raise ValueError('Refusing: customer already has vouchers or reward locks.')
    today = local_visit_date(now or datetime.now(timezone.utc))
    records = []
    for number, offset in enumerate(range(4, 0, -1), start=1):
        stamp = datetime.combine(today - timedelta(days=offset), time(12), ZoneInfo(BUSINESS_TIMEZONE))
        visit = normalize_visit(Visit(business_id=business_id, customer_id=customer_id, visit_id=str(uuid4()),
                                      visited_at=stamp, recorded_by=RECORDED_BY, visit_number=number))
        record = visit.model_dump(mode='json')
        record.update(customer_id=f'VISIT#{customer_id}#{visit.visit_id}', owner_customer_id=customer_id,
                      item_type='VISIT', acceptance_test_data=True)
        records.append(record)
    condition = 'attribute_not_exists(#count)' if 'loyalty_total_visits' not in item else '#count = :expected'
    values = {':type': 'CUSTOMER', ':active': 'active', ':total': 4, ':updated': item['updated_at']}
    if 'loyalty_total_visits' in item: values[':expected'] = 0
    update = {'Update': {'TableName': repository.table_name, 'Key': repository._key(business_id, customer_id),
              'UpdateExpression': 'SET #count = :total',
              'ConditionExpression': '#type = :type AND #status = :active AND ' + condition + ' AND #updated = :updated',
              'ExpressionAttributeNames': {'#type': 'item_type', '#status': 'status', '#count': 'loyalty_total_visits', '#updated': 'updated_at'},
              'ExpressionAttributeValues': repository._encode(values)}}
    actions = [update] + [{'Put': {'TableName': repository.table_name, 'Item': repository._encode(record),
                          'ConditionExpression': 'attribute_not_exists(#pk)', 'ExpressionAttributeNames': {'#pk': 'business_id'}}} for record in records]
    plan = {'mode': 'APPLY' if apply else 'DRY RUN', 'table': repository.table_name,
            'customer_counter_change': {'business_id': business_id, 'customer_id': customer_id,
                                        'loyalty_total_visits': {'before': 0, 'after': 4}},
            'visit_records': records, 'result': loyalty_progress(4),
            'vouchers_created': 0, 'reward_locks_created': 0, 'code_locks_created': 0}
    if apply:
        try:
            repository.client.transact_write_items(TransactItems=actions, ClientRequestToken=str(uuid4()))
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') == 'TransactionCanceledException':
                raise ValueError('Seeding rejected atomically: customer changed, visits raced, or a record exists. No partial seed was written.') from exc
            raise StorageUnavailable() from exc
        except BotoCoreError as exc: raise StorageUnavailable() from exc
    return plan


def verify(repository, business_id, customer_id, *, now=None):
    _, _, count, history, vouchers, locks = snapshot(repository, business_id, customer_id)
    today = local_visit_date(now or datetime.now(timezone.utc))
    dates = [local_visit_date(v.visited_at) for v in history]
    if (count != 4 or len(history) != 4 or [v.visit_number for v in history] != [1, 2, 3, 4]
            or len(set(dates)) != 4 or any(day >= today for day in dates)
            or any(v.recorded_by != RECORDED_BY for v in history) or vouchers or locks):
        raise ValueError('Verification failed: expected exactly four synthetic historical visits, counter 4 and no vouchers/rewards. Run before normal visit #5.')
    return {'mode': 'VERIFY (read-only)', **loyalty_progress(count), 'visits': [v.model_dump(mode='json') for v in history], 'vouchers': 0, 'reward_locks': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--business', required=True)
    parser.add_argument('--customer-id', required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Atomically write fictional acceptance visits.')
    mode.add_argument('--verify', action='store_true', help='Read-only check after seeding, before normal visit #5.')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.business): parser.error('Invalid business identifier.')
    try:
        if str(UUID(args.customer_id)) != args.customer_id: raise ValueError('Use the canonical customer UUID from Contactly.')
        settings = Settings.from_environment()
        if settings.customer_repository != 'dynamodb': raise ValueError('Set CUSTOMER_REPOSITORY=dynamodb using the existing development configuration.')
        repository = build_repository(settings)
        result = verify(repository, args.business, args.customer_id) if args.verify else seed(repository, args.business, args.customer_id, apply=args.apply)
        print(json.dumps(result, indent=2))
    except (ValueError, StorageUnavailable) as exc:
        print(str(exc) if isinstance(exc, ValueError) else 'Storage access failed. No credentials or AWS error details are displayed; verify state before retrying.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
