"""Cognito ACCESS-token boundary for registered confidential M2M clients only."""
import os
import re
import logging
import json
from dataclasses import dataclass
import jwt
from fastapi import HTTPException, Request

@dataclass(frozen=True)
class AgentPrincipal:
    subject: str
    business_id: str
    device_id: str

class AgentVerifier:
    def __init__(self, issuer=None, scope=None, keys=None):
        self.issuer=issuer; self.scope=scope
        if issuer and (not re.fullmatch(r'https://cognito-idp\.[a-z0-9-]+\.amazonaws\.com/[A-Za-z0-9_-]+',issuer)):
            raise ValueError('Print agent issuer must be a Cognito user pool issuer.')
        self.keys=keys or (jwt.PyJWKClient(issuer+'/.well-known/jwks.json',timeout=5) if issuer else None)
    @classmethod
    def from_environment(cls):
        return cls(os.getenv('PRINT_AGENT_ISSUER'),os.getenv('PRINT_AGENT_SCOPE'))
    def verify(self, token):
        if not self.issuer or not self.scope or not self.keys:
            raise HTTPException(503,'Print agent identity provider is not provisioned.')
        if len(token)>16384: raise HTTPException(401,'Invalid device token.')
        try:
            key=self.keys.get_signing_key_from_jwt(token).key
            claims=jwt.decode(token,key,algorithms=['RS256'],issuer=self.issuer,
                options={'require':['exp','iat','iss','client_id','token_use','scope'],'verify_aud':False})
            # Cognito M2M has no resource-bound aud: resource binding is exact custom
            # scope + a server-registered, confidential client_id, never a SPA audience.
            if (claims['token_use']!='access'
                    or not isinstance(claims['exp'],(int,float)) or not isinstance(claims['iat'],(int,float))
                    or not 0<claims['exp']-claims['iat']<=3600 or not isinstance(claims['scope'],str)
                    or self.scope not in claims['scope'].split()
                    or not isinstance(claims['client_id'],str) or not claims['client_id']
                    or ('aud' in claims and claims['aud']!=self.scope.rsplit('/',1)[0])):
                raise jwt.InvalidTokenError()
            return claims['client_id']
        except jwt.PyJWKClientConnectionError:
            raise HTTPException(503,'Device authentication temporarily unavailable.') from None
        except jwt.PyJWTError:
            raise HTTPException(401,'Invalid, expired or incorrectly scoped device token.',headers={'WWW-Authenticate':'Bearer'}) from None

def agent(request: Request):
    header=request.headers.get('Authorization','')
    if not header.startswith('Bearer '): raise HTTPException(401,'Device authentication required.')
    try:
        client=request.app.state.agent_verifier.verify(header[7:])
        registry=request.app.state.device_registry
        record=registry.resolve(client)
        registry.seen(record)
    except HTTPException as error:
        logging.getLogger('contactly.security').warning(json.dumps({'event':'device_access_rejected','http_status':error.status_code}))
        raise
    # Strong CAS: concurrent revocation cannot be overwritten.

    return AgentPrincipal('device:'+record['device_id'],record['business_id'],record['device_id'])
