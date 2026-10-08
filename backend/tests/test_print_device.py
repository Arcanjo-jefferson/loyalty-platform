"""No AWS, no hardware: device isolation and inherited atomic lifecycle regressions."""
import os
import unittest
from unittest.mock import patch, Mock
import asyncio
import json
from types import SimpleNamespace
from app.repository import InMemoryCustomerRepository
from app.print_lifecycle import transition
from datetime import timedelta
import test_print_queue

class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'APP_ENV':'development','PRINT_AGENT_DEV_ENABLED':'true',
            'PRINT_AGENT_DEV_SECRET':'s'*32,'PRINT_AGENT_DEV_BUSINESS':'trumps','PRINT_AGENT_DEV_ID':'test-device'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.repository=InMemoryCustomerRepository()
        with patch('app.config.build_repository'), patch('app.media_storage.build_media_storage'):
            from main import create_app
        from app.auth import InvalidAuthentication
        verifier=Mock(); verifier.verify.side_effect=InvalidAuthentication()
        app=create_app(repository=self.repository, token_verifier=verifier)
        self.client=Client(app)
        self.headers={'Authorization':'Bearer '+'s'*32}
    def test_auth_no_human_token_or_missing_secret(self):
        self.assertEqual(self.client.get('/development/print-agent/jobs').status_code,401)
        self.assertEqual(self.client.get('/development/print-agent/jobs',headers={'Authorization':'Bearer cognito-user-token'}).status_code,401)
        self.assertEqual(self.client.get('/development/print-agent/jobs',headers=self.headers).json(),[])
    def test_production_disabled_and_dynamo_disabled(self):
        with patch.dict(os.environ,{'APP_ENV':'production'}):
            self.assertEqual(self.client.get('/development/print-agent/jobs',headers=self.headers).status_code,404)
        self.client.app.state.print_service.repository=object()
        self.assertEqual(self.client.get('/development/print-agent/jobs',headers=self.headers).status_code,404)
    def test_device_cannot_use_customer_or_human_queue_api(self):
        self.assertEqual(self.client.get('/print-jobs',headers=self.headers).status_code,401)
        self.assertEqual(self.client.get('/customers',headers=self.headers).status_code,401)


    def test_bound_business_claim_and_submission_uncertain(self):
        fixture=test_print_queue.PrintTests()
        fixture.memory=True
        fixture.setUp()
        fixture.confirm()
        self.client.app.state.print_service=fixture.printing
        with patch.dict(os.environ, {'PRINT_AGENT_DEV_BUSINESS':'tenant-a'}):
            jobs=self.client.get('/development/print-agent/jobs',headers=self.headers).json()
            self.assertEqual(len(jobs),1)
            url='/development/print-agent/jobs/'+jobs[0]['print_job_id']
            claim=self.client.post(url+'/claim',json={},headers=self.headers)
            self.assertEqual(claim.status_code,200)
            token=claim.json()['claim_token']
            self.assertEqual(claim.json()['claimed_by'],'device:test-device')
            self.assertEqual(self.client.post(url+'/claim',json={},headers=self.headers).status_code,409)
            self.assertEqual(self.client.post(url+'/renew',json={'claim_token':token},headers=self.headers).status_code,200)
            self.assertEqual(self.client.post(url+'/start',json={'claim_token':token},headers=self.headers).status_code,200)
            result=self.client.post(url+'/submitted',json={'claim_token':token},headers=self.headers)
            self.assertEqual(result.json()['status'],'UNCERTAIN')
            self.assertIsNone(result.json()['printed_at'])
            self.assertEqual(result.json()['last_error'],'SPOOL_ACCEPTED_PHYSICAL_OUTPUT_UNCONFIRMED')
            self.assertEqual(self.client.get('/development/print-agent/jobs',headers=self.headers).json(),[])
        self.assertEqual(self.client.get('/development/print-agent/jobs',headers=self.headers).json(),[])

    def test_renew_stale_token_and_expiry_rejected(self):
        fixture=test_print_queue.PrintTests(); fixture.memory=True; fixture.setUp(); fixture.confirm()
        job=fixture.job(); claimed=transition(job,'claim',fixture.now,'device')
        from app.print_models import PrintJobConflict
        with self.assertRaises(PrintJobConflict): transition(claimed,'renew',fixture.now,'device','wrong')
        with self.assertRaises(PrintJobConflict): transition(claimed,'renew',fixture.now+timedelta(seconds=120),'device',claimed.claim_token)
        renewed=transition(claimed,'renew',fixture.now+timedelta(seconds=60),'device',claimed.claim_token)
        self.assertEqual(renewed.lease_until,fixture.now+timedelta(seconds=180))


class Client:
    def __init__(self, app): self.app=app
    def get(self,path,headers=None): return self.call('GET',path,None,headers)
    def post(self,path,json=None,headers=None): return self.call('POST',path,json,headers)
    def call(self,method,path,data,headers):
        async def run():
            messages=[]
            async def receive(): return {'type':'http.request','body':json.dumps(data).encode() if data is not None else b'', 'more_body':False}
            async def send(message): messages.append(message)
            scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':method,'scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'', 'headers':[(b'content-type',b'application/json')]+[(k.lower().encode(),v.encode()) for k,v in (headers or {}).items()], 'server':('localhost',80),'client':('127.0.0.1',1)}
            await self.app(scope,receive,send)
            code=next(m['status'] for m in messages if m['type']=='http.response.start')
            body=json.loads(b''.join(m.get('body',b'') for m in messages if m['type']=='http.response.body'))
            return SimpleNamespace(status_code=code,json=lambda:body)
        return asyncio.run(run())
