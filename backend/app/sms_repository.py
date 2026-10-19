"""Typed companion repository: bounded campaign outbox aggregates and atomic budget CAS.
No Scan, new table or index. All keys are within the authenticated business.
"""
from copy import deepcopy
from threading import RLock
from typing import Protocol
from uuid import uuid4
from botocore.exceptions import ClientError, BotoCoreError
from .repository import StorageUnavailable
from .print_repository import guard_transaction


class SMSConflict(Exception): pass


class SMSStore(Protocol):
    def get(self, business, key): ...
    def listing(self, business, prefix): ...
    def commit(self, business, changes, customer=None, absent=None): ...


class SMSRepository:
    def __init__(self, repository):
        self.repository = repository
        self.memory = not hasattr(repository, 'table_name')
        if self.memory:
            # State belongs to the selected customer repository, shared by services/workers.
            with repository._lock:
                if not hasattr(repository, '_sms_records'): repository._sms_records = {}
            self.records = repository._sms_records
            self.lock = repository._lock
        else:
            self.lock = RLock()

    def get(self, business, key):
        if self.memory:
            with self.lock: value = deepcopy(self.records.get((business, key)))
        else: value = self.repository._read_item(business, key)
        if value and (value.get('business_id') != business or value.get('customer_id') != key or not value.get('item_type', '').startswith('SMS_')):
            raise StorageUnavailable()
        return value

    def listing(self, business, prefix):
        if self.memory:
            with self.lock:
                return [deepcopy(v) for (b, k), v in self.records.items() if b == business and k.startswith(prefix)]
        repo = self.repository
        params = dict(TableName=repo.table_name, KeyConditionExpression='#business = :business AND begins_with(#sk, :prefix)',
                      ExpressionAttributeNames={'#business': 'business_id', '#sk': 'customer_id'},
                      ExpressionAttributeValues=repo._encode({':business': business, ':prefix': prefix}), ConsistentRead=True)
        result = []
        while True:
            page = repo._call('query', **params)
            for raw in page.get('Items', []):
                value = repo._decode(raw)
                if value.get('business_id') != business or not value.get('item_type', '').startswith('SMS_'):
                    raise StorageUnavailable()
                result.append(value)
            if not page.get('LastEvaluatedKey'): return result
            params['ExclusiveStartKey'] = page['LastEvaluatedKey']

    def commit(self, business, changes, customer=None, absent=None):
        """changes=(previous-or-None, new item); optional dispatch eligibility fence."""
        values = []
        for previous, value in changes:
            value = deepcopy(value)
            value['revision'] = str(uuid4())
            if value['business_id'] != business: raise StorageUnavailable()
            values.append((previous, value))
        if self.memory:
            with self.lock:
                for old, value in values:
                    current = self.records.get((business, value['customer_id']))
                    if (current or {}).get('revision') != (old or {}).get('revision'): raise SMSConflict()
                if absent and (business, absent) in self.records: raise SMSConflict()
                if customer:
                    current = self.repository.get(business, customer.customer_id)
                    if current is None or current.updated_at != customer.updated_at: raise SMSConflict()
                for _, value in values: self.records[(business, value['customer_id'])] = deepcopy(value)
            return
        repo = self.repository
        actions = []
        for previous, value in values:
            put = dict(TableName=repo.table_name, Item=repo._encode(value),
                       ConditionExpression='#kind = :kind AND #revision = :revision' if previous else 'attribute_not_exists(#pk)',
                       ExpressionAttributeNames={'#kind': 'item_type', '#revision': 'revision'} if previous else {'#pk': 'business_id'})
            if previous: put['ExpressionAttributeValues'] = repo._encode({':kind': previous['item_type'], ':revision': previous['revision']})
            actions.append({'Put': put})
        if customer:
            actions.append({'ConditionCheck': dict(TableName=repo.table_name, Key=repo._key(business, customer.customer_id),
                ConditionExpression='#kind = :kind AND #revision = :revision',
                ExpressionAttributeNames={'#kind': 'item_type', '#revision': 'updated_at'},
                ExpressionAttributeValues=repo._encode({':kind': 'CUSTOMER', ':revision': customer.model_dump(mode='json')['updated_at']}))})
        if absent:
            actions.append({'ConditionCheck': dict(TableName=repo.table_name, Key=repo._key(business, absent),
                ConditionExpression='attribute_not_exists(#pk)', ExpressionAttributeNames={'#pk': 'business_id'})})
        guard_transaction(actions)
        try: repo.client.transact_write_items(TransactItems=actions, ClientRequestToken=str(uuid4()))
        except ClientError as error:
            if error.response['Error']['Code'] in {'TransactionCanceledException', 'TransactionConflictException'}: raise SMSConflict() from None
            raise StorageUnavailable() from error
        except BotoCoreError as error: raise StorageUnavailable() from error
