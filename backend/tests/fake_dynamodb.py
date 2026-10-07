"""Small atomic DynamoDB test double; no credentials, network or AWS resources.

Supports only the expressions used by this adapter. Unknown expressions fail tests.
"""
from copy import deepcopy
from threading import RLock
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError


class FakeDynamoDB:
    def __init__(self, page_size=100):
        self.items = {}
        self.lock = RLock()
        self.calls = []
        self.page_size = page_size
        self.injected_errors = []
        self.serialize = TypeSerializer()
        self.deserialize = TypeDeserializer()

    def encode(self, data):
        return {key: self.serialize.serialize(value) for key, value in data.items()}

    def decode(self, data):
        return {key: self.deserialize.deserialize(value) for key, value in data.items()}

    def key(self, item):
        return item['business_id'], item['customer_id']

    def get_item(self, **params):
        with self.lock:
            self.calls.append(('get_item', deepcopy(params)))
            item = self.items.get(self.key(self.decode(params['Key'])))
            return {'Item': self.encode(deepcopy(item))} if item else {}

    def query(self, **params):
        with self.lock:
            self.calls.append(('query', deepcopy(params)))
            assert params['KeyConditionExpression'] in {'#business = :business', '#business = :business AND begins_with(#sk, :prefix)'}
            values = self.decode(params['ExpressionAttributeValues'])
            keys = sorted(key for key in self.items if key[0] == values[':business'])
            if ':prefix' in values: keys = [key for key in keys if key[1].startswith(values[':prefix'])]
            if params.get('ExclusiveStartKey'):
                after = self.key(self.decode(params['ExclusiveStartKey']))
                keys = [key for key in keys if key > after]
            page_keys = keys[:self.page_size]
            result = {'Items': [self.encode(deepcopy(self.items[key])) for key in page_keys if ':customer_type' not in values or self.items[key].get('item_type') == values[':customer_type']]}
            if len(keys) > len(page_keys):
                last = page_keys[-1]
                result['LastEvaluatedKey'] = self.encode({'business_id': last[0], 'customer_id': last[1]})
            return result

    def _condition(self, action, item):
        expression = action['ConditionExpression']
        values = self.decode(action.get('ExpressionAttributeValues', {}))
        if expression == 'attribute_not_exists(#pk)':
            return item is None
        if expression == '#owner = :owner':
            return item is not None and item.get('owner_customer_id') == values[':owner']
        if expression == '#phone = :old_phone AND #updated = :expected AND #type = :customer_type':
            return item is not None and item.get('phone') == values[':old_phone'] and item.get('updated_at') == values[':expected'] and item.get('item_type') == values[':customer_type']
        if expression == '#type = :type AND #qr = :qr':
            return item is not None and item.get('item_type') == values[':type'] and item.get('qr_token') == values[':qr']
        if expression == 'attribute_not_exists(#pk) OR (#type = :type AND #owner = :owner)':
            return item is None or (item.get('item_type') == values[':type'] and item.get('owner_customer_id') == values[':owner'])
        if expression == '#type = :type AND #status = :active AND #expiry > :instant':
            return item is not None and item.get('item_type') == values[':type'] and item.get('status') == values[':active'] and item.get('expires_at_micros', 0) > values[':instant']
        prefix = '#type = :type AND #status = :active AND '
        if expression.startswith(prefix):
            suffix = expression[len(prefix):]
            if suffix.endswith(' AND #updated = :updated'):
                if item is None or item.get('updated_at') != values[':updated']: return False
                suffix = suffix.removesuffix(' AND #updated = :updated')
            assert suffix in {'attribute_not_exists(#count)', '#count = :expected'}
            return item is not None and item.get('item_type') == values[':type'] and item.get('status') == values[':active'] and (('loyalty_total_visits' not in item) if suffix == 'attribute_not_exists(#count)' else item.get('loyalty_total_visits') == values[':expected'])
        raise AssertionError(f'Unsupported test expression: {expression}')

    def transact_write_items(self, **params):
        with self.lock:
            self.calls.append(('transact_write_items', deepcopy(params)))
            if self.injected_errors:
                raise self.injected_errors.pop(0)
            actions = params['TransactItems']
            keys, reasons = [], []
            for request in actions:
                kind, action = next(iter(request.items()))
                key = self.key(self.decode(action['Item'] if kind == 'Put' else action['Key']))
                keys.append(key)
                reasons.append({'Code': 'None' if self._condition(action, self.items.get(key)) else 'ConditionalCheckFailed'})
            assert len(keys) == len(set(keys)), 'A DynamoDB transaction cannot target an item twice'
            if any(reason['Code'] != 'None' for reason in reasons):
                raise ClientError({'Error': {'Code': 'TransactionCanceledException', 'Message': 'test cancellation'}, 'CancellationReasons': reasons}, 'TransactWriteItems')
            staged = deepcopy(self.items)
            for request, key in zip(actions, keys):
                kind, action = next(iter(request.items()))
                if kind == 'Put':
                    staged[key] = self.decode(action['Item'])
                elif kind == 'Delete':
                    staged.pop(key, None)
                elif kind == 'Update':
                    assert action['UpdateExpression'].startswith('SET ')
                    values = self.decode(action['ExpressionAttributeValues'])
                    for assignment in action['UpdateExpression'][4:].split(', '):
                        name, value = assignment.split(' = ')
                        staged[key][action['ExpressionAttributeNames'][name]] = values[value]
                elif kind != 'ConditionCheck':
                    raise AssertionError(f'Unsupported transaction action: {kind}')
            self.items = staged
            return {}

    def update_item(self, **params):
        with self.lock:
            self.calls.append(('update_item', deepcopy(params)))
            if self.injected_errors:
                raise self.injected_errors.pop(0)
            key = self.key(self.decode(params['Key']))
            item = self.items.get(key)
            values = self.decode(params['ExpressionAttributeValues'])
            names = params['ExpressionAttributeNames']
            assert params['UpdateExpression'] == 'SET #media = :media'
            field = names['#media']
            assert field.startswith('media_')
            condition = params['ConditionExpression']
            valid = item is not None and item.get('item_type') == values[':type']
            if condition == '#type = :type AND attribute_not_exists(#media)':
                valid = valid and field not in item
            elif condition == '#type = :type AND #media.#revision = :revision':
                valid = valid and item.get(field, {}).get('revision') == values[':revision']
            else:
                raise AssertionError('Unsupported media condition')
            if not valid:
                raise ClientError({'Error': {'Code': 'ConditionalCheckFailedException', 'Message': 'fixture'}}, 'UpdateItem')
            self.items[key][field] = deepcopy(values[':media'])
            return {}
