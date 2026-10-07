"""Private QR lifecycle plus an opaque public routing directory (no table Scan)."""
import secrets
from datetime import datetime, timezone
from uuid import uuid4
from botocore.exceptions import ClientError, BotoCoreError
from .repository import ConcurrentModification, StorageUnavailable

PUBLIC_PARTITION = '!PUBLIC_QR'  # Rejected by verified business-claim validation.


class QRNotFound(Exception): pass


class DynamoQRMixin:
    def qr_details(self, business_id, customer_id):
        item = self._read_item(business_id, customer_id)
        if not item or item.get('item_type') != 'CUSTOMER': raise QRNotFound()
        return self._customer(item), item.get('public_qr_ref')

    def public_qr_token(self, reference):
        pointer = self._read_item(PUBLIC_PARTITION, 'PUBLIC#' + reference)
        if not pointer or pointer.get('item_type') != 'PUBLIC_QR': raise QRNotFound()
        customer, current_ref = self.qr_details(pointer['owner_business_id'], pointer['owner_customer_id'])
        if current_ref != reference or customer.status != 'active': raise QRNotFound()
        return customer.qr_token

    def manage_qr(self, business_id, customer_id, *, expected_token=None):
        rotating = expected_token is not None
        for attempt in range(self.MAX_TRANSACTION_ATTEMPTS):
            customer, old_ref = self.qr_details(business_id, customer_id)
            if rotating and customer.qr_token != expected_token: raise ConcurrentModification()
            if not rotating and old_ref: return customer, old_ref
            reference = secrets.token_urlsafe(32)
            token = secrets.token_urlsafe(32) if rotating else customer.qr_token
            names = {'#type': 'item_type', '#qr': 'qr_token', '#ref': 'public_qr_ref', '#updated': 'updated_at'}
            values = {':type': 'CUSTOMER', ':old': customer.qr_token, ':ref': reference,
                      ':expected': customer.model_dump(mode='json')['updated_at']}
            condition = '#type = :type AND #qr = :old AND #updated = :expected'
            expression = 'SET #ref = :ref'
            if old_ref:
                values[':old_ref'] = old_ref
                condition += ' AND #ref = :old_ref'
            else: condition += ' AND attribute_not_exists(#ref)'
            if rotating:
                values.update({':new': token, ':now': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')})
                expression += ', #qr = :new, #updated = :now'
            transaction = [{'Update': {'TableName': self.table_name, 'Key': self._key(business_id, customer_id),
                            'UpdateExpression': expression, 'ConditionExpression': condition,
                            'ExpressionAttributeNames': names, 'ExpressionAttributeValues': self._encode(values)}},
                           {'Put': {'TableName': self.table_name, 'Item': self._encode({
                            'business_id': PUBLIC_PARTITION, 'customer_id': 'PUBLIC#' + reference,
                            'item_type': 'PUBLIC_QR', 'owner_business_id': business_id, 'owner_customer_id': customer_id}),
                            'ConditionExpression': 'attribute_not_exists(#pk)', 'ExpressionAttributeNames': {'#pk': 'business_id'}}}]
            if rotating:
                transaction.extend([self._qr_claim(customer.model_copy(update={'qr_token': token})),
                    {'Delete': {'TableName': self.table_name, 'Key': self._key(business_id, 'QR#' + customer.qr_token),
                                'ConditionExpression': '#owner = :owner', 'ExpressionAttributeNames': {'#owner': 'owner_customer_id'},
                                'ExpressionAttributeValues': self._encode({':owner': customer_id})}}])
                if old_ref:
                    transaction.append({'Delete': {'TableName': self.table_name, 'Key': self._key(PUBLIC_PARTITION, 'PUBLIC#' + old_ref),
                                       'ConditionExpression': '#owner = :owner AND #business = :business',
                                       'ExpressionAttributeNames': {'#owner': 'owner_customer_id', '#business': 'owner_business_id'},
                                       'ExpressionAttributeValues': self._encode({':owner': customer_id, ':business': business_id})}})
            try:
                self.client.transact_write_items(TransactItems=transaction, ClientRequestToken=str(uuid4()))
                updated = customer.model_copy(update={'qr_token': token})
                return updated, reference
            except ClientError as exc:
                code = exc.response.get('Error', {}).get('Code')
                if code not in {'TransactionCanceledException', 'TransactionConflictException'}: raise StorageUnavailable() from exc
                if rotating:
                    current, _ = self.qr_details(business_id, customer_id)
                    if current.qr_token != expected_token: raise ConcurrentModification() from exc
                if attempt + 1 == self.MAX_TRANSACTION_ATTEMPTS: raise ConcurrentModification() from exc
            except BotoCoreError as exc: raise StorageUnavailable() from exc
        raise ConcurrentModification()
