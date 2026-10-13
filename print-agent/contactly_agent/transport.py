"""Outbound-only isolated development transport; never accepts human credentials."""
import json
import os
from urllib.parse import urlparse, quote
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirects are forbidden for device credentials.')

def direct_open(request, timeout):
    return build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout)

class HTTPTransport:
    def __init__(self, url, timeout=10, opener=direct_open):
        parsed = urlparse(url)
        if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or parsed.path.rstrip('/') != '/development/print-agent' or parsed.query or parsed.fragment
                or parsed.username or parsed.password):
            raise ValueError('Only isolated loopback development transport is available; production auth is blocked.')
        self.url, self.timeout, self.opener = url.rstrip('/'), timeout, opener
    def request(self, path, data=None):
        secret = os.environ.get('CONTACTLY_AGENT_DEV_SECRET', '')
        if len(secret) < 32: raise ValueError('Development device secret is missing.')
        request = Request(self.url + path, data=None if data is None else json.dumps(data).encode(),
                          headers={'Authorization': 'Bearer ' + secret, 'Content-Type': 'application/json'})
        with self.opener(request, timeout=self.timeout) as response:
            return json.load(response)
    def jobs(self): return self.request('/jobs')
    def action(self, job_id, action, token=None):
        return self.request('/jobs/' + quote(job_id, safe='') + '/' + action,
                            {} if token is None else {'claim_token': token})

class SecureTransport(HTTPTransport):
    """HTTPS only. Refresh credentials before calls; never replay lifecycle writes."""
    def __init__(self,url,provider,timeout=10,opener=direct_open):
        from .oauth import https_url
        self.url=https_url(url)
        if urlparse(self.url).path.rstrip('/')!='/print-agent':
            raise ValueError('Expected dedicated /print-agent backend boundary.')
        self.provider,self.timeout,self.opener=provider,timeout,opener
    def request(self,path,data=None):
        from urllib.error import HTTPError
        request=Request(self.url+path,data=None if data is None else json.dumps(data).encode(),
            headers={'Authorization':'Bearer '+self.provider.token(),'Content-Type':'application/json'})
        try:
            with self.opener(request,timeout=self.timeout) as response: return json.load(response)
        except HTTPError as error:
            if error.code==401: self.provider.invalidate()
            # No automatic write replay; worker's durable intent protects lost start.
            raise
