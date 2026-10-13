"""DynamoDB adapter: customer records and phone locks share a business partition."""
import random
import time
from uuid import uuid4
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import TypeAdapter, ValidationError
from datetime import datetime
from .models import Customer, CustomerInput
from .repository import ConcurrentModification, DuplicatePhone, DuplicateQR, StorageUnavailable


from .loyalty_repository import DynamoLoyaltyMixin
from .voucher_repository import DynamoVoucherMixin
from .qr_repository import DynamoQRMixin
from .print_repository import DynamoPrintMixin
from .raffle_repository import DynamoRaffleMixin


class DynamoDBCustomerRepository(DynamoLoyaltyMixin, DynamoVoucherMixin, DynamoQRMixin, DynamoRaffleMixin, DynamoPrintMixin):
    PHONE_PREFIX = 'PHONE#'
    MAX_TRANSACTION_ATTEMPTS = 3

    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self._serializer = TypeSerializer()
        self._deserializer = TypeDeserializer()

    def _encode(self, item):
        return {name: self._serializer.serialize(value) for name, value in item.items()}

    def _decode(self, item):
        return {name: self._deserializer.deserialize(value) for name, value in item.items()}

    def _key(self, business_id, customer_id):
        return self._encode({'business_id': business_id, 'customer_id': customer_id})

    def _call(self, operation, **kwargs):
        try:
            return getattr(self.client, operation)(**kwargs)
        except (ClientError, BotoCoreError) as exc:
            raise StorageUnavailable() from exc

    def _read_item(self, business_id, customer_id):
        response = self._call('get_item', TableName=self.table_name,
                              Key=self._key(business_id, customer_id), ConsistentRead=True)
        item = response.get('Item')
        return self._decode(item) if item else None

    def _customer(self, item):
        # Storage-only attributes and future document references are not API fields.
        try:
            return Customer.model_validate({name: item[name] for name in Customer.model_fields if name in item})
        except (ValidationError, KeyError, TypeError) as exc:
            raise StorageUnavailable() from exc

    def get(self, business_id, customer_id):
        if customer_id.startswith((self.PHONE_PREFIX, 'QR#', 'VISIT#', 'VOUCHER#', 'VCODE#', 'REWARD#', 'RAFFLE#', 'RAFFLE_DATE#', 'PRINT#', 'DEVICE#', 'CLIENT#')):
            return None
        item = self._read_item(business_id, customer_id)
        return self._customer(item) if item and item.get('item_type') == 'CUSTOMER' else None

    def list(self, business_id):
        customers = []
        params = {
            'TableName': self.table_name,
            'KeyConditionExpression': '#business = :business',
            'FilterExpression': '#type = :customer_type',
            'ExpressionAttributeNames': {'#business': 'business_id', '#type': 'item_type'},
            'ExpressionAttributeValues': self._encode({':business': business_id, ':customer_type': 'CUSTOMER'}),
            'ConsistentRead': True,
        }
        while True:
            page = self._call('query', **params)
            for raw in page.get('Items', []):
                item = self._decode(raw)
                if item.get('item_type') == 'CUSTOMER' and not item['customer_id'].startswith((self.PHONE_PREFIX, 'QR#', 'VISIT#', 'VOUCHER#', 'VCODE#', 'REWARD#', 'RAFFLE#', 'RAFFLE_DATE#', 'PRINT#', 'DEVICE#', 'CLIENT#')):
                    customers.append(self._customer(item))
            last_key = page.get('LastEvaluatedKey')
            if not last_key:
                return customers
            params['ExclusiveStartKey'] = last_key

    def _phone_claim(self, customer):
        return {'Put': {
            'TableName': self.table_name,
            'Item': self._encode({
                'business_id': customer.business_id,
                'customer_id': self.PHONE_PREFIX + customer.phone,
                'item_type': 'PHONE_LOCK',
                'owner_customer_id': customer.customer_id,
            }),
            'ConditionExpression': 'attribute_not_exists(#pk)',
            'ExpressionAttributeNames': {'#pk': 'business_id'},
        }}

    def save(self, customer, *, expected_updated_at=None):
        data = customer.model_dump(mode='json')
        if expected_updated_at is None:
            transaction = [self._phone_claim(customer), {'Put': {
                'TableName': self.table_name,
                'Item': self._encode({**data, 'item_type': 'CUSTOMER'}),
                'ConditionExpression': 'attribute_not_exists(#pk)',
                'ExpressionAttributeNames': {'#pk': 'business_id'},
            }}, self._qr_claim(customer)]
            changing_phone = True
        else:
            old = self.get(customer.business_id, customer.customer_id)
            if old is None or old.updated_at != expected_updated_at:
                raise ConcurrentModification()
            changing_phone = old.phone != customer.phone
            # Update only managed editable fields; keep immutable fields and future metadata.
            editable = [*CustomerInput.model_fields, 'consent_timestamp', 'updated_at']
            names = {f'#f{i}': name for i, name in enumerate(editable)}
            values = {f':v{i}': data[name] for i, name in enumerate(editable)}
            names.update({'#phone': 'phone', '#updated': 'updated_at', '#type': 'item_type'})
            values.update({':old_phone': old.phone,
                           ':expected': TypeAdapter(datetime).dump_python(expected_updated_at, mode='json'),
                           ':customer_type': 'CUSTOMER'})
            update = {'Update': {
                'TableName': self.table_name,
                'Key': self._key(customer.business_id, customer.customer_id),
                'UpdateExpression': 'SET ' + ', '.join(f'#f{i} = :v{i}' for i in range(len(editable))),
                'ConditionExpression': '#phone = :old_phone AND #updated = :expected AND #type = :customer_type',
                'ExpressionAttributeNames': names,
                'ExpressionAttributeValues': self._encode(values),
            }}
            old_lock = {
                'TableName': self.table_name,
                'Key': self._key(customer.business_id, self.PHONE_PREFIX + old.phone),
                'ConditionExpression': '#owner = :owner',
                'ExpressionAttributeNames': {'#owner': 'owner_customer_id'},
                'ExpressionAttributeValues': self._encode({':owner': customer.customer_id}),
            }
            transaction = [self._phone_claim(customer), update, {'Delete': old_lock}] if changing_phone else [
                {'ConditionCheck': old_lock}, update,
            ]
        self._transact(transaction, customer, changing_phone)

    def _transact(self, transaction, customer, claiming_phone):
        # Same token/payload across conflict retries and SDK network retries.
        token = str(uuid4())
        for attempt in range(self.MAX_TRANSACTION_ATTEMPTS):
            try:
                self.client.transact_write_items(TransactItems=transaction, ClientRequestToken=token)
                return
            except ClientError as exc:
                code = exc.response.get('Error', {}).get('Code')
                reasons = exc.response.get('CancellationReasons', [])
                reason_codes = [reason.get('Code', 'None') for reason in reasons]
                if code == 'TransactionCanceledException':
                    if reason_codes and reason_codes[0] == 'ConditionalCheckFailed' and claiming_phone:
                        raise DuplicatePhone() from exc
                    if len(reason_codes) > 1 and reason_codes[1] == 'ConditionalCheckFailed':
                        raise ConcurrentModification() from exc
                    if len(reason_codes) > 2 and 'Put' in transaction[2] and reason_codes[2] == 'ConditionalCheckFailed':
                        raise DuplicateQR() from exc
                    if not reasons:
                        # Some SDK/service responses omit reasons. Read only the lock key,
                        # never scan or parse raw AWS error messages.
                        lock = self._read_item(customer.business_id, self.PHONE_PREFIX + customer.phone)
                        if claiming_phone and lock and lock.get('owner_customer_id') != customer.customer_id:
                            raise DuplicatePhone() from exc
                        qr = self._read_item(customer.business_id, 'QR#' + customer.qr_token)
                        if len(transaction) == 3 and 'Put' in transaction[2] and qr and qr.get('owner_customer_id') != customer.customer_id:
                            raise DuplicateQR() from exc
                conflict = code == 'TransactionConflictException' or (
                    code == 'TransactionCanceledException' and 'TransactionConflict' in reason_codes
                    and not any(reason not in {'None', 'TransactionConflict'} for reason in reason_codes)
                )
                if conflict and attempt + 1 < self.MAX_TRANSACTION_ATTEMPTS:
                    time.sleep(random.uniform(0.01, 0.04) * (2 ** attempt))
                    continue
                raise StorageUnavailable() from exc
            except BotoCoreError as exc:
                raise StorageUnavailable() from exc

    def get_media(self, business_id, customer_id, kind):
        item = self._read_item(business_id, customer_id)
        if not item or item.get('item_type') != 'CUSTOMER':
            return None
        return item.get('media_' + kind)

    def save_media(self, business_id, customer_id, kind, metadata, *, expected_revision):
        names = {'#media': 'media_' + kind, '#type': 'item_type'}
        values = {':media': metadata, ':type': 'CUSTOMER'}
        condition = '#type = :type AND attribute_not_exists(#media)'
        if expected_revision is not None:
            names['#revision'] = 'revision'
            values[':revision'] = expected_revision
            condition = '#type = :type AND #media.#revision = :revision'
        try:
            self.client.update_item(TableName=self.table_name, Key=self._key(business_id, customer_id),
                                    UpdateExpression='SET #media = :media', ConditionExpression=condition,
                                    ExpressionAttributeNames=names, ExpressionAttributeValues=self._encode(values))
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') == 'ConditionalCheckFailedException':
                raise ConcurrentModification() from exc
            raise StorageUnavailable() from exc
        except BotoCoreError as exc:
            raise StorageUnavailable() from exc
