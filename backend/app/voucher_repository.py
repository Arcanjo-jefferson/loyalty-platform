"""Private single-table reward locks, voucher code indexes and redemption CAS."""
import time
from uuid import uuid4
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError
from .models import Voucher
from .repository import StorageUnavailable
from .voucher_rules import reward_key, effective_voucher


class VoucherNotFound(Exception): pass
class VoucherNotRedeemable(Exception): pass


def voucher_key(customer_id, voucher_id):
    return f'VOUCHER#{customer_id}#{voucher_id}'


class DynamoVoucherMixin:
    def reward_exists(self, business_id, key):
        return self._read_item(business_id, key) is not None

    def _voucher(self, item):
        if not item or item.get('item_type') != 'VOUCHER': raise VoucherNotFound()
        try:
            return Voucher.model_validate({**{name: item[name] for name in Voucher.model_fields if name in item},
                                           'customer_id': item['owner_customer_id']})
        except (ValidationError, KeyError, TypeError) as exc: raise StorageUnavailable() from exc

    def get_voucher(self, business_id, customer_id, voucher_id):
        voucher = self._voucher(self._read_item(business_id, voucher_key(customer_id, voucher_id)))
        if voucher.business_id != business_id or voucher.customer_id != customer_id or voucher.voucher_id != voucher_id:
            raise StorageUnavailable()
        return voucher

    def lookup_voucher(self, business_id, code):
        lock = self._read_item(business_id, 'VCODE#' + code)
        if not lock or lock.get('item_type') != 'VOUCHER_CODE': raise VoucherNotFound()
        try:
            voucher = self.get_voucher(business_id, lock['owner_customer_id'], lock['voucher_id'])
        except (KeyError, TypeError) as exc: raise StorageUnavailable() from exc
        if voucher.voucher_code != code: raise StorageUnavailable()
        return voucher

    def vouchers(self, business_id, customer_id):
        params = {'TableName': self.table_name,
                  'KeyConditionExpression': '#business = :business AND begins_with(#sk, :prefix)',
                  'ExpressionAttributeNames': {'#business': 'business_id', '#sk': 'customer_id'},
                  'ExpressionAttributeValues': self._encode({':business': business_id, ':prefix': f'VOUCHER#{customer_id}#'}),
                  'ConsistentRead': True}
        result = []
        while True:
            page = self._call('query', **params)
            for raw in page.get('Items', []):
                voucher = self._voucher(self._decode(raw))
                if voucher.business_id != business_id or voucher.customer_id != customer_id: raise StorageUnavailable()
                result.append(voucher)
            if not page.get('LastEvaluatedKey'): return sorted(result, key=lambda v: v.issued_at, reverse=True)
            params['ExclusiveStartKey'] = page['LastEvaluatedKey']

    def _reward_transactions(self, vouchers):
        actions = []
        for voucher in vouchers:
            data = voucher.model_dump(mode='json')
            data.update(customer_id=voucher_key(voucher.customer_id, voucher.voucher_id),
                        owner_customer_id=voucher.customer_id, item_type='VOUCHER',
                        expires_at_micros=int(voucher.expires_at.timestamp() * 1_000_000))
            for item in [data,
                         {'business_id': voucher.business_id, 'customer_id': reward_key(voucher),
                          'item_type': 'REWARD_LOCK', 'voucher_id': voucher.voucher_id,
                          'qualifying_visit_id': voucher.qualifying_visit_id},
                         {'business_id': voucher.business_id, 'customer_id': 'VCODE#' + voucher.voucher_code,
                          'item_type': 'VOUCHER_CODE', 'owner_customer_id': voucher.customer_id,
                          'voucher_id': voucher.voucher_id}]:
                actions.append({'Put': {'TableName': self.table_name, 'Item': self._encode(item),
                                'ConditionExpression': 'attribute_not_exists(#pk)',
                                'ExpressionAttributeNames': {'#pk': 'business_id'}}})
        return actions

    def redeem_voucher(self, business_id, customer_id, voucher_id, now, subject):
        voucher = self.get_voucher(business_id, customer_id, voucher_id)
        if effective_voucher(voucher, now).status != 'ACTIVE': raise VoucherNotRedeemable()
        update = {'Update': {'TableName': self.table_name, 'Key': self._key(business_id, voucher_key(customer_id, voucher_id)),
                  'UpdateExpression': 'SET #status = :redeemed, #at = :now, #by = :subject',
                  'ConditionExpression': '#type = :type AND #status = :active AND #expiry > :instant',
                  'ExpressionAttributeNames': {'#type': 'item_type', '#status': 'status', '#expiry': 'expires_at_micros',
                                               '#at': 'redeemed_at', '#by': 'redeemed_by'},
                  'ExpressionAttributeValues': self._encode({':type': 'VOUCHER', ':active': 'ACTIVE', ':redeemed': 'REDEEMED',
                                                             ':now': now.isoformat().replace('+00:00', 'Z'), ':instant': int(now.timestamp() * 1_000_000), ':subject': subject})}}
        for attempt in range(self.MAX_TRANSACTION_ATTEMPTS):
            try:
                self.client.transact_write_items(TransactItems=[update], ClientRequestToken=str(uuid4()))
                return voucher.model_copy(update={'status': 'REDEEMED', 'redeemed_at': now, 'redeemed_by': subject})
            except ClientError as exc:
                code = exc.response.get('Error', {}).get('Code')
                reasons = exc.response.get('CancellationReasons', [])
                conditional = code == 'TransactionCanceledException' and any(r.get('Code') == 'ConditionalCheckFailed' for r in reasons)
                conflict = code == 'TransactionConflictException' or (code == 'TransactionCanceledException' and any(r.get('Code') == 'TransactionConflict' for r in reasons))
                if conditional: raise VoucherNotRedeemable() from exc
                if conflict or (code == 'TransactionCanceledException' and not reasons):
                    current = self.get_voucher(business_id, customer_id, voucher_id)
                    if effective_voucher(current, now).status != 'ACTIVE': raise VoucherNotRedeemable() from exc
                    if attempt + 1 < self.MAX_TRANSACTION_ATTEMPTS:
                        time.sleep(0.02 * (2 ** attempt))
                        continue
                raise StorageUnavailable() from exc
            except BotoCoreError as exc: raise StorageUnavailable() from exc
        raise StorageUnavailable()
