"""Same-table customer history and immutable date projection; no Scan/GSI."""
from pydantic import ValidationError
from .models import RaffleEntry
from .raffle import raffle_key, raffle_date_key
from .repository import StorageUnavailable


class DynamoRaffleMixin:
    def _raffle_transactions(self, entry):
        data = entry.model_dump(mode='json')
        # The date projection repeats only immutable, non-PII entry fields.
        return [{'Put': {'TableName': self.table_name,
                        'Item': self._encode({**data, 'customer_id': key,
                                             'owner_customer_id': entry.customer_id, 'item_type': kind}),
                        'ConditionExpression': 'attribute_not_exists(#pk)',
                        'ExpressionAttributeNames': {'#pk': 'business_id'}}}
                for key, kind in [(raffle_key(entry), 'RAFFLE_ENTRY'),
                                  (raffle_date_key(entry), 'RAFFLE_DATE_INDEX')]]

    def _raffle_query(self, business_id, prefix, *, customer_id=None, raffle_date=None):
        kind = 'RAFFLE_ENTRY' if customer_id is not None else 'RAFFLE_DATE_INDEX'
        params = {'TableName': self.table_name,
                  'KeyConditionExpression': '#business = :business AND begins_with(#sk, :prefix)',
                  'ExpressionAttributeNames': {'#business': 'business_id', '#sk': 'customer_id'},
                  'ExpressionAttributeValues': self._encode({':business': business_id, ':prefix': prefix}),
                  'ConsistentRead': True}
        entries = []
        while True:
            page = self._call('query', **params)
            for raw in page.get('Items', []):
                item = self._decode(raw)
                try:
                    entry = RaffleEntry.model_validate({
                        **{name: item[name] for name in RaffleEntry.model_fields if name in item},
                        'customer_id': item['owner_customer_id'], 'item_type': 'RAFFLE_ENTRY'})
                    key = raffle_key(entry) if customer_id is not None else raffle_date_key(entry)
                    if (item.get('item_type') != kind or entry.business_id != business_id
                            or item['customer_id'] != key or entry.raffle_entry_id != entry.visit_id
                            or (customer_id is not None and entry.customer_id != customer_id)
                            or (raffle_date is not None and entry.raffle_date != raffle_date)):
                        raise ValueError('Invalid raffle record')
                except (ValidationError, ValueError, KeyError, TypeError) as exc:
                    raise StorageUnavailable() from exc
                entries.append(entry)
            if not page.get('LastEvaluatedKey'):
                return sorted(entries, key=lambda entry: (entry.created_at, entry.raffle_entry_id), reverse=True)
            params['ExclusiveStartKey'] = page['LastEvaluatedKey']

    def raffle_entries(self, business_id, customer_id):
        return self._raffle_query(business_id, f'RAFFLE#{customer_id}#', customer_id=customer_id)

    def raffle_entries_for_date(self, business_id, raffle_date):
        return self._raffle_query(business_id, f'RAFFLE_DATE#{raffle_date.isoformat()}#', raffle_date=raffle_date)
