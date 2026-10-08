"""Server-controlled device registry; no provider secrets are stored here.
Reserved directory partition maps confidential OAuth client IDs to tenant devices.
Provisioning is an explicit operator action after provider-side verification.
"""
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from uuid import uuid4
from botocore.exceptions import ClientError, BotoCoreError
from fastapi import HTTPException
from .repository import StorageUnavailable

DIRECTORY = '!PRINT_DEVICES'

def now(): return datetime.now(timezone.utc).isoformat()

class DeviceRegistry:
    def __init__(self, repository):
        self.repository=repository
        self.memory=not hasattr(repository, 'table_name')
        self.records={}; self.clients={}; self.lock=RLock()
    def get(self, business, identity):
        if self.memory:
            with self.lock: value=deepcopy(self.records.get((business,identity)))
        else: value=self.repository._read_item(business,'DEVICE#'+identity)
        if not value or value.get('item_type')!='PRINT_DEVICE' or value.get('business_id')!=business:
            raise HTTPException(404,'Print device not found.')
        return value
    def listing(self, business):
        if self.memory:
            with self.lock: return [deepcopy(v) for (b,_),v in self.records.items() if b==business]
        repo=self.repository
        params=dict(TableName=repo.table_name, KeyConditionExpression='#business = :business AND begins_with(#sk, :prefix)',
            ExpressionAttributeNames={'#business':'business_id','#sk':'customer_id'},
            ExpressionAttributeValues=repo._encode({':business':business,':prefix':'DEVICE#'}),ConsistentRead=True)
        result=[]
        while True:
            page=repo._call('query',**params)
            result.extend(repo._decode(v) for v in page.get('Items',[]) if repo._decode(v).get('item_type')=='PRINT_DEVICE')
            if not page.get('LastEvaluatedKey'): return result
            params['ExclusiveStartKey']=page['LastEvaluatedKey']
    def save(self, previous, record, client=None):
        with self.lock:
            if self.memory:
                old=self.records.get((record['business_id'],record['device_id']))
                if (old or {}).get('revision')!=(previous or {}).get('revision'):
                    raise HTTPException(409,'Device changed. Refresh before continuing.')
                if client and client in self.clients: raise HTTPException(409,'OAuth client already assigned.')
                self.records[(record['business_id'],record['device_id'])]=deepcopy(record)
                if client: self.clients[client]=(record['business_id'],record['device_id'])
                return
            repo=self.repository
            put={'TableName':repo.table_name,'Item':repo._encode(record),
                'ConditionExpression':'#kind = :kind AND #revision = :revision' if previous else 'attribute_not_exists(#pk)',
                'ExpressionAttributeNames':{'#kind':'item_type','#revision':'revision'} if previous else {'#pk':'business_id'}}
            if previous: put['ExpressionAttributeValues']=repo._encode({':kind':'PRINT_DEVICE',':revision':previous['revision']})
            actions=[{'Put':put}]
            if client:
                actions.append({'Put':dict(TableName=repo.table_name,
                    Item=repo._encode({'business_id':DIRECTORY,'customer_id':'CLIENT#'+client,'item_type':'PRINT_DEVICE_CLIENT',
                        'owner_business_id':record['business_id'],'device_id':record['device_id']}),
                    ConditionExpression='attribute_not_exists(#pk)',ExpressionAttributeNames={'#pk':'business_id'})})
            try: repo.client.transact_write_items(TransactItems=actions,ClientRequestToken=str(uuid4()))
            except ClientError as error:
                if error.response['Error']['Code'] in {'TransactionCanceledException','ConditionalCheckFailedException'}:
                    raise HTTPException(409,'Device changed or OAuth client already assigned.') from None
                raise StorageUnavailable() from error
            except BotoCoreError as error: raise StorageUnavailable() from error
    def register(self, business, actor, label):
        identity=str(uuid4()); stamp=now()
        record=dict(business_id=business,customer_id='DEVICE#'+identity,item_type='PRINT_DEVICE',device_id=identity,
            label=label,status='PENDING_PROVISIONING',client_id=None,revision=str(uuid4()),last_seen=None,
            events=[dict(action='REGISTERED_PENDING',at=stamp,actor=actor)])
        self.save(None,record); return record
    def update(self, business, identity, actor, action):
        old=self.get(business,identity); value=deepcopy(old)
        value.update(status='DISABLED' if action=='disable' else 'PENDING_PROVISIONING',revision=str(uuid4()))
        # Old client binding retained as tombstone; its tokens fail status/client checks.
        if action=='rotate': value['client_id']=None
        value['events'].append(dict(action='REVOKED' if action=='disable' else 'ROTATION_PENDING',at=now(),actor=actor))
        self.save(old,value); return value
    def activate(self, business, identity, client_id, actor):
        """Operator only, after external confidential-client provisioning; no API exposes this."""
        import re
        if not re.fullmatch(r'[A-Za-z0-9]{1,128}',client_id):
            raise ValueError('Invalid confidential client ID.')
        old=self.get(business,identity)
        if old['status']!='PENDING_PROVISIONING' or old['client_id']:
            raise HTTPException(409,'Device is not pending provisioning.')
        value=deepcopy(old); value.update(status='ACTIVE',client_id=client_id,revision=str(uuid4()))
        value['events'].append(dict(action='PROVISIONING_VERIFIED',at=now(),actor=actor))
        self.save(old,value,client_id); return value
    def resolve(self, client):
        if self.memory:
            with self.lock: binding=self.clients.get(client)
        else:
            row=self.repository._read_item(DIRECTORY,'CLIENT#'+client)
            binding=(row['owner_business_id'],row['device_id']) if row and row.get('item_type')=='PRINT_DEVICE_CLIENT' else None
        if not binding: raise HTTPException(403,'Device is not registered or active.')
        record=self.get(*binding)
        if record['status']!='ACTIVE' or record['client_id']!=client:
            raise HTTPException(403,'Device is not registered or active.')
        return record
    def seen(self, record):
        value=deepcopy(record); value.update(last_seen=now(),revision=str(uuid4()))
        self.save(record,value)
