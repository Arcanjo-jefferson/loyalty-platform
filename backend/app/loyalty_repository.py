"""Single-table QR index and atomically counted immutable visit history."""
import random
import time
from uuid import uuid4
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError
from .models import Visit
from .raffle import raffle_for_visit
from .visit_dates import normalize_visit, local_visit_date
from .repository import ConcurrentModification, DuplicateQR, DuplicateVisit, InactiveCustomer, StorageUnavailable


class DynamoLoyaltyMixin:
    def _qr_claim(self, customer):
        return {'Put': {
            'TableName': self.table_name,
            'Item': self._encode({'business_id': customer.business_id, 'customer_id': 'QR#' + customer.qr_token,
                                  'item_type': 'QR_LOCK', 'owner_customer_id': customer.customer_id}),
            'ConditionExpression': 'attribute_not_exists(#pk)',
            'ExpressionAttributeNames': {'#pk': 'business_id'},
        }}

    def find_active_by_qr(self, business_id, qr_token):
        lock = self._read_item(business_id, 'QR#' + qr_token)
        if not lock or lock.get('item_type') != 'QR_LOCK': return None
        owner = lock.get('owner_customer_id')
        customer = self.get(business_id, owner) if isinstance(owner, str) else None
        return customer if customer and customer.qr_token == qr_token and customer.status == 'active' else None

    def ensure_qr_lock(self, customer):
        """Idempotent backfill; never overwrite another owner or change a token."""
        claim = self._qr_claim(customer)
        claim['Put'].update(ConditionExpression='attribute_not_exists(#pk) OR (#type = :type AND #owner = :owner)',
                            ExpressionAttributeNames={'#pk': 'business_id', '#type': 'item_type', '#owner': 'owner_customer_id'},
                            ExpressionAttributeValues=self._encode({':type': 'QR_LOCK', ':owner': customer.customer_id}))
        check = {'ConditionCheck': {'TableName': self.table_name, 'Key': self._key(customer.business_id, customer.customer_id),
                 'ConditionExpression': '#type = :type AND #qr = :qr',
                 'ExpressionAttributeNames': {'#type': 'item_type', '#qr': 'qr_token'},
                 'ExpressionAttributeValues': self._encode({':type': 'CUSTOMER', ':qr': customer.qr_token})}}
        try:
            self.client.transact_write_items(TransactItems=[check, claim], ClientRequestToken=str(uuid4()))
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') == 'TransactionCanceledException':
                reasons = exc.response.get('CancellationReasons', [])
                if reasons and reasons[0].get('Code') == 'ConditionalCheckFailed': raise ConcurrentModification() from exc
                if len(reasons) > 1 and reasons[1].get('Code') == 'ConditionalCheckFailed': raise DuplicateQR() from exc
            raise StorageUnavailable() from exc
        except BotoCoreError as exc: raise StorageUnavailable() from exc

    def _visit_state(self, business_id, customer_id):
        item = self._read_item(business_id, customer_id)
        if not item or item.get('item_type') != 'CUSTOMER': raise ConcurrentModification()
        count = item.get('loyalty_total_visits', 0)
        # Counter corruption must fail closed, never reset history/progress.
        try:
            invalid = (isinstance(count, bool) or count != int(count) or count < 0)
        except (TypeError, ValueError, OverflowError) as exc:
            raise StorageUnavailable() from exc
        if invalid:
            raise StorageUnavailable()
        return item, int(count)

    def total_visits(self, business_id, customer_id):
        return self._visit_state(business_id, customer_id)[1]

    def visits(self, business_id, customer_id):
        params = {'TableName': self.table_name,
                  'KeyConditionExpression': '#business = :business AND begins_with(#sk, :prefix)',
                  'ExpressionAttributeNames': {'#business': 'business_id', '#sk': 'customer_id'},
                  'ExpressionAttributeValues': self._encode({':business': business_id, ':prefix': f'VISIT#{customer_id}#'}),
                  'ConsistentRead': True}
        history = []
        while True:
            page = self._call('query', **params)
            for raw in page.get('Items', []):
                item = self._decode(raw)
                if item.get('item_type') != 'VISIT' or item.get('owner_customer_id') != customer_id:
                    raise StorageUnavailable()
                try:
                    history.append(normalize_visit(Visit.model_validate({**{name: item[name] for name in Visit.model_fields if name in item}, 'customer_id': item['owner_customer_id']})))
                except (ValidationError, ValueError, TypeError, KeyError) as exc: raise StorageUnavailable() from exc
            if not page.get('LastEvaluatedKey'): return sorted(history, key=lambda visit: visit.visit_number)
            params['ExclusiveStartKey'] = page['LastEvaluatedKey']

    def record_visit(self, visit, reward_factory=None):
        visit = normalize_visit(visit)
        # Read counter BEFORE strongly consistent history. A competing commit
        # either appears in history or invalidates the transaction's counter CAS.
        for attempt in range(self.MAX_TRANSACTION_ATTEMPTS):
            item, count = self._visit_state(visit.business_id, visit.customer_id)
            if item.get('status') != 'active': raise InactiveCustomer()
            if any(local_visit_date(previous.visited_at) == visit.local_visit_date
                   for previous in self.visits(visit.business_id, visit.customer_id)):
                raise DuplicateVisit()
            saved = visit.model_copy(update={'visit_number': count + 1})
            vouchers = reward_factory(self._customer(item), saved, count + 1, self.reward_exists) if reward_factory else []
            if len({voucher.voucher_code for voucher in vouchers}) != len(vouchers):
                # A transaction cannot address a code-lock item twice. Regenerate
                # both candidate codes before writing anything.
                if attempt + 1 < self.MAX_TRANSACTION_ATTEMPTS: continue
                raise StorageUnavailable()
            data = saved.model_dump(mode='json')
            data.update(customer_id=f'VISIT#{visit.customer_id}#{visit.visit_id}', owner_customer_id=visit.customer_id, item_type='VISIT')
            count_condition = 'attribute_not_exists(#count)' if count == 0 and 'loyalty_total_visits' not in item else '#count = :expected'
            values = {':type': 'CUSTOMER', ':active': 'active', ':total': count + 1}
            if count_condition == '#count = :expected': values[':expected'] = count
            update = {'Update': {'TableName': self.table_name, 'Key': self._key(visit.business_id, visit.customer_id),
                      'UpdateExpression': 'SET #count = :total',
                      'ConditionExpression': '#type = :type AND #status = :active AND ' + count_condition,
                      'ExpressionAttributeNames': {'#type': 'item_type', '#status': 'status', '#count': 'loyalty_total_visits'},
                      'ExpressionAttributeValues': self._encode(values)}}
            put = {'Put': {'TableName': self.table_name, 'Item': self._encode(data),
                   'ConditionExpression': 'attribute_not_exists(#pk)', 'ExpressionAttributeNames': {'#pk': 'business_id'}}}
            # Reward eligibility uses the actual persisted DOB. If a manager edits
            # the customer concurrently, retry the whole decision using that DOB.
            if reward_factory:
                update['Update']['ConditionExpression'] += ' AND #updated = :updated'
                update['Update']['ExpressionAttributeNames']['#updated'] = 'updated_at'
                update['Update']['ExpressionAttributeValues'].update(self._encode({':updated': item['updated_at']}))
            entry = raffle_for_visit(saved)
            transaction = {'TransactItems': [update, put] + self._raffle_transactions(entry) + self._reward_transactions(vouchers), 'ClientRequestToken': str(uuid4())}
            try:
                self.client.transact_write_items(**transaction)
                return self._customer(item), saved, count + 1, vouchers, entry
            except ClientError as exc:
                code = exc.response.get('Error', {}).get('Code')
                reasons = exc.response.get('CancellationReasons', [])
                if code == 'TransactionCanceledException' and len(reasons) > 1 and reasons[1].get('Code') == 'ConditionalCheckFailed':
                    raise ConcurrentModification() from exc
                conditional = code == 'TransactionCanceledException' and (not reasons or any(reason.get('Code') == 'ConditionalCheckFailed' for reason in reasons))
                conflict = code == 'TransactionConflictException' or (code == 'TransactionCanceledException' and any(reason.get('Code') == 'TransactionConflict' for reason in reasons))
                if not (conditional or conflict): raise StorageUnavailable() from exc
                if attempt + 1 < self.MAX_TRANSACTION_ATTEMPTS:
                    time.sleep(random.uniform(0.01, 0.03) * (2 ** attempt))
                    continue
                # Re-read to classify a daily duplicate or deactivation racing our write.
                current, _ = self._visit_state(visit.business_id, visit.customer_id)
                if current.get('status') != 'active': raise InactiveCustomer() from exc
                if any(local_visit_date(previous.visited_at) == visit.local_visit_date
                       for previous in self.visits(visit.business_id, visit.customer_id)):
                    raise DuplicateVisit() from exc
                raise ConcurrentModification() from exc
            except BotoCoreError as exc: raise StorageUnavailable() from exc
        raise ConcurrentModification()
