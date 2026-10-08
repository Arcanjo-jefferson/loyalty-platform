"""Signed local JWTs, fake DynamoDB and local simulation; never live AWS/hardware."""
import time
import sys
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from app.auth import Role, UserContext, InvalidAuthentication
from app.print_agent_auth import AgentVerifier
from app.print_devices import DeviceRegistry
import test_print_device
import test_print_queue

ISSUER='https://cognito-idp.eu-west-1.amazonaws.com/eu-west-1_fixture'
SCOPE='contactly-print/queue'

class SecureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    def setUp(self):
        fixture=test_print_queue.PrintTests(); fixture.memory=True; fixture.setUp(); fixture.confirm()
        self.fixture=fixture
        keys=Mock(); keys.get_signing_key_from_jwt.return_value=SimpleNamespace(key=self.key.public_key())
        self.verifier=AgentVerifier(ISSUER,SCOPE,keys)
        with patch('app.config.build_repository'), patch('app.media_storage.build_media_storage'):
            from main import create_app
        human=Mock(); human.verify.side_effect=InvalidAuthentication()
        self.human=human
        self.app=create_app(fixture.repo,human,media_storage=Mock(),agent_verifier=self.verifier)
        self.app.state.print_service=fixture.printing
        self.registry=self.app.state.device_registry
        self.device=self.registry.register('tenant-a','owner','Fictional Windows device')
        self.registry.activate('tenant-a',self.device['device_id'],'clientA','test-operator')
        self.client=test_print_device.Client(self.app)
    def token(self,**changes):
        claims=dict(iss=ISSUER,exp=int(time.time())+300,iat=int(time.time()),token_use='access',client_id='clientA',scope=SCOPE)
        claims.update(changes)
        return jwt.encode(claims,self.key,algorithm='RS256',headers={'kid':'fixture'})
    def call(self,path='/print-agent/jobs',method='GET',data=None,token=None):
        return self.client.call(method,path,data,{'Authorization':'Bearer '+(token or self.token())})
    def test_fictional_visit_authenticated_simulation_no_physical_completion(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'print-agent'))
        from contactly_agent.printer import SimulationPrinter
        queue=self.call(); self.assertEqual(queue.status_code,200); self.assertEqual(len(queue.json()),1)
        identity=queue.json()[0]['print_job_id']; url='/print-agent/jobs/'+identity
        claim=self.call(url+'/claim','POST',{}); self.assertEqual(claim.status_code,200)
        with tempfile.TemporaryDirectory() as folder:
            printer=SimulationPrinter(folder); printer.submit(claim.json(),printer.prepare(claim.json()))
            self.assertEqual(len(list(Path(folder).glob('*.txt'))),1)
        # Test-only pre-output release. Never calls start/complete/submitted.
        result=self.call(url+'/fail','POST',{'claim_token':claim.json()['claim_token']})
        self.assertEqual(result.json()['status'],'RETRYABLE'); self.assertIsNone(result.json()['printed_at'])
        self.assertEqual(len(self.fixture.jobs()),1)
        self.assertIsNotNone(self.registry.get('tenant-a',self.device['device_id'])['last_seen'])
    def test_unregistered_disabled_rotated_devices_rejected(self):
        self.assertEqual(self.call(token=self.token(client_id='unknown')).status_code,403)
        self.registry.update('tenant-a',self.device['device_id'],'owner','disable')
        self.assertEqual(self.call().status_code,403)
        second=self.registry.register('tenant-a','owner','Second')
        self.registry.activate('tenant-a',second['device_id'],'clientB','operator')
        self.registry.update('tenant-a',second['device_id'],'owner','rotate')
        self.assertEqual(self.call(token=self.token(client_id='clientB')).status_code,403)
        self.registry.activate('tenant-a',second['device_id'],'clientC','operator')
        self.assertEqual(self.call(token=self.token(client_id='clientC')).status_code,200)
    def test_tenant_isolation_ignores_business_claim(self):
        other=self.registry.register('tenant-b','owner','Other')
        self.registry.activate('tenant-b',other['device_id'],'clientOther','operator')
        token=self.token(client_id='clientOther',**{'custom:business_id':'tenant-a'})
        self.assertEqual(self.call(token=token).json(),[])
        url='/print-agent/jobs/'+self.fixture.job().print_job_id+'/claim'
        self.assertEqual(self.call(url,'POST',{},token).status_code,404)
    def test_no_customer_admin_manager_or_completion_permissions(self):
        for path in ['/customers','/print-jobs','/auth/me','/print-devices']:
            self.assertEqual(self.call(path).status_code,401)
        url='/print-agent/jobs/'+self.fixture.job().print_job_id
        for action in ['review','complete','reprint']:
            self.assertEqual(self.call(url+'/'+action,'POST',{'claim_token':'x'*43}).status_code,404)
    def test_purpose_scope_expiry_issuer_audience_signature(self):
        for changes in [dict(token_use='id'),dict(scope='other/queue'),dict(exp=int(time.time())-1),
                        dict(iss='https://invalid.example'),dict(aud='wrong'),dict(iat=int(time.time())+60),dict(exp=int(time.time())+7200)]:
            self.assertEqual(self.call(token=self.token(**changes)).status_code,401)
        forged=jwt.encode(dict(iss=ISSUER,exp=int(time.time())+300,iat=int(time.time()),token_use='access',client_id='clientA',scope=SCOPE),self.other,algorithm='RS256')
        self.assertEqual(self.call(token=forged).status_code,401)
        with self.assertRaises(HTTPException): self.verifier.verify(jwt.encode({'token_use':'access'},self.key,algorithm='RS256'))
    def test_owner_only_management_and_pending_workflow(self):
        for role in [Role.MANAGER,Role.STAFF]:
            self.human.verify.side_effect=None
            self.human.verify.return_value=UserContext('human',None,'tenant-a',(),role)
            self.assertEqual(self.client.get('/print-devices',headers={'Authorization':'Bearer human'}).status_code,403)
        self.human.verify.return_value=UserContext('owner',None,'tenant-a',(),Role.OWNER)
        value=self.client.post('/print-devices',json={'label':'New device'},headers={'Authorization':'Bearer human'})
        self.assertEqual(value.status_code,201); self.assertEqual(value.json()['status'],'PENDING_PROVISIONING')
        self.assertIsNone(value.json()['client_id']); self.assertNotIn('secret',str(value.json()))
        self.assertEqual(self.client.post('/print-devices',json={'label':'Device','business_id':'tenant-b'},headers={'Authorization':'Bearer human'}).status_code,422)
        other=self.registry.register('tenant-b','owner','Other')
        self.assertEqual(self.client.post('/print-devices/'+other['device_id']+'/disable',json={},headers={'Authorization':'Bearer human'}).status_code,404)
    def test_atomic_claim_multiple_devices_and_device_fence(self):
        second=self.registry.register('tenant-a','owner','Second'); self.registry.activate('tenant-a',second['device_id'],'clientB','operator')
        url='/print-agent/jobs/'+self.fixture.job().print_job_id
        first=self.call(url+'/claim','POST',{}); self.assertEqual(first.status_code,200)
        self.assertEqual(self.call(url+'/claim','POST',{},self.token(client_id='clientB')).status_code,409)
        self.assertEqual(self.call(url+'/start','POST',{'claim_token':first.json()['claim_token']},self.token(client_id='clientB')).status_code,409)
        self.assertEqual(first.json()['claimed_by'],'device:'+self.device['device_id'])
    def test_dynamo_registry_directory_conditional_rotation_no_scan(self):
        fixture=test_print_queue.PrintTests(); fixture.setUp()
        registry=DeviceRegistry(fixture.repo)
        device=registry.register('tenant-a','owner','Dynamo fake')
        registry.activate('tenant-a',device['device_id'],'fakeClient','operator')
        self.assertEqual(registry.resolve('fakeClient')['business_id'],'tenant-a')
        self.assertEqual(len(registry.listing('tenant-a')),1)
        registry.seen(registry.resolve('fakeClient'))
        registry.update('tenant-a',device['device_id'],'owner','rotate')
        with self.assertRaises(HTTPException): registry.resolve('fakeClient')
        registry.activate('tenant-a',device['device_id'],'newClient','operator')
        with self.assertRaises(HTTPException): registry.activate('tenant-a',registry.register('tenant-a','owner','Duplicate')['device_id'],'newClient','operator')
        self.assertEqual(len(fixture.repo.list('tenant-a')),1)

    def test_revocation_cannot_be_overwritten_by_last_seen(self):
        snapshot=self.registry.resolve('clientA')
        self.registry.update('tenant-a',self.device['device_id'],'owner','disable')
        with self.assertRaises(HTTPException): self.registry.seen(snapshot)
        self.assertEqual(self.registry.get('tenant-a',self.device['device_id'])['status'],'DISABLED')

    def test_missing_auth_unprovisioned_provider_and_wrong_algorithm(self):
        self.assertEqual(self.client.get('/print-agent/jobs').status_code,401)
        with self.assertRaises(HTTPException) as failure: AgentVerifier().verify('test')
        self.assertEqual(failure.exception.status_code,503)
        forged=jwt.encode(dict(iss=ISSUER,exp=int(time.time())+300,iat=int(time.time()),token_use='access',client_id='clientA',scope=SCOPE),'fictional-hmac-key-at-least-32-characters',algorithm='HS256')
        self.assertEqual(self.call(token=forged).status_code,401)
