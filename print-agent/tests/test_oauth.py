"""Mock HTTPS identity provider and Windows vault; no real secrets or network."""
import io
import json
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError
from contactly_agent.oauth import TokenProvider, WindowsCredentialStore
from contactly_agent.transport import SecureTransport

class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.clock=0; self.requests=[]; self.store=Mock(); self.store.read.return_value='fictional-secret'
        def opener(request,timeout):
            self.requests.append((request,timeout))
            return io.StringIO(json.dumps(dict(access_token='test-token',token_type='Bearer',expires_in=300,scope='contactly-print/queue')))
        self.provider=TokenProvider('https://fixture.auth.eu-west-1.amazoncognito.com/oauth2/token','fixtureClient','contactly-print/queue',self.store,opener=opener,clock=lambda:self.clock)
    def test_client_credentials_scoped_cached_and_renewed(self):
        self.assertEqual(self.provider.token(),'test-token'); self.provider.token()
        self.assertEqual(len(self.requests),1)
        self.assertIn(b'grant_type=client_credentials',self.requests[0][0].data)
        self.assertIn(b'scope=contactly-print%2Fqueue',self.requests[0][0].data)
        self.assertTrue(self.requests[0][0].get_header('Authorization').startswith('Basic '))
        self.clock=271; self.provider.token(); self.assertEqual(len(self.requests),2)
    def test_https_required_no_fallback(self):
        for url in ['http://localhost:8000/print-agent','https://user:pass@fixture/print-agent','https://fixture/print-agent?business=other']:
            with self.assertRaises(ValueError): SecureTransport(url,self.provider)
        with self.assertRaises(ValueError): TokenProvider('http://fixture/oauth2/token','id','scope',self.store)
    def test_401_invalidates_without_replaying_write(self):
        calls=[]
        def opener(request,timeout): calls.append(request); raise HTTPError('url',401,'Expired',{},None)
        transport=SecureTransport('https://backend.example/print-agent',self.provider,opener=opener)
        with self.assertRaises(HTTPError): transport.action('job','start','fence')
        self.assertEqual(len(calls),1); self.assertIsNone(self.provider.cached)
    def test_revoked_provider_error_no_fallback(self):
        def opener(*args,**kwargs): raise HTTPError('url',400,'invalid_client',{},None)
        self.provider.opener=opener
        with self.assertRaises(HTTPError): self.provider.token()
        self.assertIsNone(self.provider.cached)
    def test_bad_identity_response_rejected(self):
        for value in [dict(access_token='value',token_type='Basic',expires_in=300),dict(access_token='value',token_type='Bearer',expires_in=86400),dict(access_token='value',token_type='Bearer',expires_in=300,scope='other')]:
            self.provider.opener=lambda *args,**kwargs:io.StringIO(json.dumps(value))
            with self.assertRaises(ValueError): self.provider.token()
    def test_windows_os_protected_storage_roundtrip(self):
        api=Mock(); api.CRED_TYPE_GENERIC=1; api.CRED_PERSIST_LOCAL_MACHINE=2
        vault=WindowsCredentialStore('Contactly/PrintAgent/fixture-device',api)
        vault.write('fictional-secret')
        data=api.CredWrite.call_args.args[0]
        self.assertEqual(data['CredentialBlob'],'fictional-secret'.encode('utf-16-le'))
        api.CredRead.return_value=data
        self.assertEqual(vault.read(),'fictional-secret')
    def test_https_queue_request_has_no_business_or_human_identity(self):
        calls=[]
        def opener(request,timeout): calls.append(request); return io.StringIO('[]')
        transport=SecureTransport('https://backend.example/print-agent',self.provider,opener=opener)
        self.assertEqual(transport.jobs(),[])
        self.assertEqual(calls[0].full_url,'https://backend.example/print-agent/jobs')
        self.assertEqual(calls[0].get_header('Authorization'),'Bearer test-token')
