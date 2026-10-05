"""Verified Cognito identity and reusable business-role authorization."""
import os
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Annotated
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


class Role(str, Enum):
    OWNER = 'OWNER'
    MANAGER = 'MANAGER'
    STAFF = 'STAFF'


@dataclass(frozen=True)
class UserContext:
    subject: str
    email: str | None
    business_id: str
    groups: tuple[str, ...]
    role: Role


class InvalidAuthentication(Exception):
    pass


class AuthenticationUnavailable(Exception):
    pass


class InvalidMembership(Exception):
    pass


# Normalize ASCII case against an explicit allowlist, ordered by precedence.
# No whitespace trimming, substring matching, or additional role aliases.
GROUP_ROLES = {'owner': Role.OWNER, 'manager': Role.MANAGER, 'staff': Role.STAFF}
logger = logging.getLogger('uvicorn.error')


def membership_diagnostic(claims, role, reason):
    # Explicit local-development opt-in. Never log claims, identities or tokens.
    if os.getenv('APP_ENV') == 'development' and os.getenv('AUTH_DIAGNOSTICS') == 'true':
        logger.warning(
            'Auth membership: reason=%s business_claim_present=%s business_claim_valid=%s '
            'groups_claim_present=%s groups_claim_valid=%s recognized_role=%s',
            reason, 'custom:business_id' in claims,
            isinstance(claims.get('custom:business_id'), str) and
            bool(re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', claims['custom:business_id'])),
            'cognito:groups' in claims,
            isinstance(claims.get('cognito:groups'), list) and
            all(isinstance(group, str) for group in claims['cognito:groups']),
            role.value if role else 'none',
        )


def user_from_claims(claims):
    business = claims.get('custom:business_id')
    groups = claims.get('cognito:groups')
    groups_valid = isinstance(groups, list) and all(isinstance(group, str) for group in groups)
    normalized_groups = {group.lower() for group in groups if group.isascii()} if groups_valid else set()
    role = next((role for group, role in GROUP_ROLES.items() if group in normalized_groups), None)
    reason = None
    if 'custom:business_id' not in claims:
        reason = 'missing_business_claim'
    elif not isinstance(business, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', business):
        reason = 'invalid_business_claim'
    elif 'cognito:groups' not in claims:
        reason = 'missing_groups_claim'
    elif not groups_valid:
        reason = 'invalid_groups_claim'
    elif role is None:
        reason = 'no_recognized_role'
    membership_diagnostic(claims, role, reason or 'authorized')
    if reason:
        raise InvalidMembership()
    subject = claims.get('sub')
    if not isinstance(subject, str) or not subject:
        raise InvalidAuthentication()
    email = claims.get('email')
    return UserContext(subject, email if isinstance(email, str) else None, business, tuple(groups), role)


class CognitoVerifier:
    def __init__(self, pool_id, client_id, region, jwks_client=None):
        self.configured = bool(pool_id and client_id and region)
        self.issuer = f'https://cognito-idp.{region}.amazonaws.com/{pool_id}'
        self.client_id = client_id
        self.jwks = jwks_client or jwt.PyJWKClient(f'{self.issuer}/.well-known/jwks.json', lifespan=300, timeout=5)

    @classmethod
    def from_environment(cls):
        return cls(os.getenv('COGNITO_USER_POOL_ID', ''), os.getenv('COGNITO_APP_CLIENT_ID', ''), os.getenv('COGNITO_REGION', os.getenv('AWS_REGION', 'eu-west-1')))

    def verify(self, token):
        if not self.configured:
            raise AuthenticationUnavailable()
        try:
            header = jwt.get_unverified_header(token)
            if header.get('alg') != 'RS256' or not isinstance(header.get('kid'), str) or not header['kid']:
                raise InvalidAuthentication()
            # Header is used only to select a trusted key, never as identity or a URL.
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=['RS256'], audience=self.client_id,
                                issuer=self.issuer, options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'token_use']}, leeway=0)
            if claims.get('token_use') != 'id' or claims.get('aud') != self.client_id:
                raise InvalidAuthentication()
            return user_from_claims(claims)
        except jwt.PyJWKClientConnectionError as exc:
            raise AuthenticationUnavailable() from exc
        except jwt.PyJWTError as exc:
            raise InvalidAuthentication() from exc


bearer = HTTPBearer(auto_error=False)


def authenticated_user(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if not credentials or credentials.scheme.lower() != 'bearer':
        raise HTTPException(401, 'Authentication required.', headers={'WWW-Authenticate': 'Bearer'})
    try:
        return request.app.state.token_verifier.verify(credentials.credentials)
    except InvalidAuthentication:
        raise HTTPException(401, 'Invalid or expired session. Please sign in again.', headers={'WWW-Authenticate': 'Bearer'}) from None
    except InvalidMembership:
        raise HTTPException(403, 'Your account does not have business access. Contact your administrator.') from None
    except AuthenticationUnavailable:
        raise HTTPException(503, 'Authentication is temporarily unavailable. Check backend configuration or try again.') from None


def require_roles(*roles):
    def authorize(user: Annotated[UserContext, Depends(authenticated_user)]):
        if user.role not in roles:
            raise HTTPException(403, 'You do not have permission for this action.')
        return user
    return authorize


require_owner = require_roles(Role.OWNER)
require_management = require_roles(Role.OWNER, Role.MANAGER)
require_customer_access = require_roles(Role.OWNER, Role.MANAGER, Role.STAFF)
# Future sensitive document endpoints must use require_management. No document API exists.


def authorize_customer_status(user, previous_status, new_status):
    if previous_status != new_status and user.role not in {Role.OWNER, Role.MANAGER}:
        raise HTTPException(403, 'Only Owner or Manager may change customer status.')
