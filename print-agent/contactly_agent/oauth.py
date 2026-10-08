"""OAuth client credentials; Windows Credential Manager, in-memory token cache."""
import base64
import getpass
import json
import os
import threading
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request
from .transport import direct_open


def https_url(url):
    value=urlparse(url)
    if value.scheme!='https' or not value.hostname or value.username or value.password or value.query or value.fragment:
        raise ValueError('An explicit HTTPS URL without credentials, query or fragment is required.')
    return url.rstrip('/')

class WindowsCredentialStore:
    def __init__(self,target,api=None):
        if not target.startswith('Contactly/PrintAgent/'):
            raise ValueError('Use a Contactly/PrintAgent/ credential target.')
        if api is None:
            if os.name!='nt': raise RuntimeError('Production credentials require Windows Credential Manager.')
            import win32cred
            api=win32cred
        self.target,self.api=target,api
    def read(self):
        value=self.api.CredRead(self.target,self.api.CRED_TYPE_GENERIC,0)['CredentialBlob']
        return value.decode('utf-16-le') if isinstance(value,bytes) else value
    def write(self,secret):
        if not secret: raise ValueError('Empty credential refused.')
        self.api.CredWrite(dict(Type=self.api.CRED_TYPE_GENERIC,TargetName=self.target,
            CredentialBlob=secret.encode('utf-16-le'),Persist=self.api.CRED_PERSIST_LOCAL_MACHINE,UserName='Contactly device'),0)

class TokenProvider:
    def __init__(self,url,client_id,scope,store,timeout=10,opener=direct_open,clock=time.monotonic):
        self.url=https_url(url)
        if urlparse(self.url).path!='/oauth2/token': raise ValueError('Expected Cognito OAuth token endpoint.')
        if not client_id or not scope: raise ValueError('Client ID and exact queue scope are required.')
        self.client_id,self.scope,self.store=client_id,scope,store
        self.timeout,self.opener,self.clock=timeout,opener,clock
        self.cached=None; self.until=0; self.lock=threading.Lock()
    def invalidate(self):
        with self.lock: self.cached=None; self.until=0
    def token(self):
        with self.lock:
            if self.cached and self.clock()<self.until: return self.cached
            secret=self.store.read()
            # OAuth client_secret_basic percent-encodes credentials before Base64.
            from urllib.parse import quote_plus
            auth=base64.b64encode((quote_plus(self.client_id)+':'+quote_plus(secret)).encode()).decode()
            request=Request(self.url,data=urlencode({'grant_type':'client_credentials','scope':self.scope}).encode(),
                headers={'Authorization':'Basic '+auth,'Content-Type':'application/x-www-form-urlencoded'})
            started=self.clock()
            with self.opener(request,timeout=self.timeout) as response: value=json.load(response)
            lifetime=value.get('expires_in')
            if (value.get('token_type','').lower()!='bearer' or not isinstance(value.get('access_token'),str)
                    or not value['access_token'] or not isinstance(lifetime,int) or not 60<=lifetime<=3600
                    or (value.get('scope') is not None and self.scope not in value['scope'].split())):
                raise ValueError('Invalid identity provider response.')
            self.cached=value['access_token']; self.until=started+lifetime-30
            return self.cached


def provision():
    import argparse
    parser=argparse.ArgumentParser(description='Store separately provisioned device secret in Windows vault; never calls AWS')
    parser.add_argument('--target',required=True)
    args=parser.parse_args()
    WindowsCredentialStore(args.target).write(getpass.getpass('Provisioned device client secret: '))

if __name__=='__main__': provision()
