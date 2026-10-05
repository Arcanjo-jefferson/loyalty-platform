import asyncio
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from app.auth import CognitoVerifier, InvalidAuthentication, InvalidMembership, Role, UserContext, user_from_claims, require_owner, require_management
from app.repository import InMemoryCustomerRepository


async def request(app, method='GET', path='/customers', token=None, data=None, query=''):
    messages = []
    async def receive():
        return {'type': 'http.request', 'body': json.dumps(data).encode() if data is not None else b'', 'more_body': False}
    async def send(message):
        messages.append(message)
    headers = [(b'content-type', b'application/json')]
    if token is not None:
        headers.append((b'authorization', f'Bearer {token}'.encode()))
    await app({'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(), 'query_string': query.encode(), 'headers': headers, 'server': ('test', 80), 'client': ('test', 1)}, receive, send)
    status = next(m['status'] for m in messages if m['type'] == 'http.response.start')
    body = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
    return status, json.loads(body)


class JWTVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        keys = Mock()
        keys.get_signing_key_from_jwt.return_value = SimpleNamespace(key=self.private.public_key())
        self.verifier = CognitoVerifier('test-pool', 'test-client', 'eu-west-1', keys)
        self.keys = keys

    def claims(self, **changes):
        return {'iss': self.verifier.issuer, 'aud': 'test-client', 'sub': 'test-subject', 'iat': int(time.time()), 'exp': int(time.time()) + 300, 'token_use': 'id', 'custom:business_id': 'test-business', 'cognito:groups': ['Staff'], 'email': 'fictional@example.invalid', **changes}

    def token(self, claims=None, key=None):
        return jwt.encode(claims or self.claims(), key or self.private, algorithm='RS256', headers={'kid': 'trusted-test-key'})

    def test_signed_identity_and_precedence(self):
        user = self.verifier.verify(self.token())
        self.assertEqual(user.role, Role.STAFF)
        self.assertEqual(user.business_id, 'test-business')
        self.assertEqual(user.subject, 'test-subject')
        self.assertEqual(self.verifier.verify(self.token(self.claims(**{'cognito:groups': ['Staff', 'Manager', 'Owner']}))).role, Role.OWNER)
        self.assertEqual(self.verifier.verify(self.token(self.claims(**{'cognito:groups': ['Staff', 'Manager']}))).role, Role.MANAGER)

    def test_real_world_groups_and_case_normalization_allowlist(self):
        for group, role in [(name, role) for base, role in [('owner', Role.OWNER), ('manager', Role.MANAGER), ('staff', Role.STAFF)] for name in [base, base.title(), base.upper(), base.swapcase()]]:
            with self.subTest(group=group):
                user = self.verifier.verify(self.token(self.claims(**{'custom:business_id': 'trumps', 'cognito:groups': [group]})))
                self.assertEqual(user.role, role)
                self.assertEqual(user.business_id, 'trumps')
        for group in ['OwnerAdmin', ' Owner ', 'business-owner', 'ſtaff', 'admin']:
            with self.subTest(group=group), self.assertRaises(InvalidMembership):
                self.verifier.verify(self.token(self.claims(**{'cognito:groups': [group]})))

    def test_lowercase_and_mixed_group_precedence(self):
        for groups, role in [(['staff', 'manager', 'owner'], Role.OWNER),
                             (['owner', 'staff', 'manager'], Role.OWNER),
                             (['staff', 'manager'], Role.MANAGER),
                             (['MANAGER', 'staff', 'Owner'], Role.OWNER),
                             (['unrecognized', 'staff'], Role.STAFF)]:
            with self.subTest(groups=groups):
                user = self.verifier.verify(self.token(self.claims(**{'cognito:groups': groups})))
                self.assertEqual(user.role, role)
                self.assertEqual(user.groups, tuple(groups))

    def test_identity_endpoint_with_signed_claims_and_401_403_distinction(self):
        with patch('app.config.build_repository'), patch('app.media_storage.build_media_storage'):
            from main import create_app
        app = create_app(InMemoryCustomerRepository(), self.verifier)
        for group in ['owner', 'manager', 'staff', 'Owner', 'Manager', 'Staff']:
            status, identity = asyncio.run(request(app, path='/auth/me', token=self.token(self.claims(**{'custom:business_id': 'trumps', 'cognito:groups': [group]}))))
            self.assertEqual(status, 200)
            self.assertEqual(identity['role'], group.upper())
            self.assertEqual(identity['business_id'], 'trumps')
        claims = self.claims(); claims.pop('custom:business_id')
        self.assertEqual(asyncio.run(request(app, path='/auth/me', token=self.token(claims)))[0], 403)
        claims = self.claims(); claims.pop('cognito:groups')
        self.assertEqual(asyncio.run(request(app, path='/auth/me', token=self.token(claims)))[0], 403)
        self.assertEqual(asyncio.run(request(app, path='/auth/me', token=self.token(self.claims(token_use='access'))))[0], 401)
        self.assertEqual(asyncio.run(request(app, path='/auth/me'))[0], 401)

    def test_development_diagnostics_are_safe_and_disabled_elsewhere(self):
        sentinel = 'sensitive-sentinel-do-not-log'
        cases = [({}, 'missing_business_claim'), ({'custom:business_id': ''}, 'invalid_business_claim'),
                 ({'custom:business_id': 'trumps'}, 'missing_groups_claim'),
                 ({'custom:business_id': 'trumps', 'cognito:groups': 'Owner'}, 'invalid_groups_claim'),
                 ({'custom:business_id': 'trumps', 'cognito:groups': [sentinel]}, 'no_recognized_role')]
        for membership, reason in cases:
            claims = {'sub': sentinel, 'email': sentinel, **membership}
            with patch.dict('os.environ', {'APP_ENV': 'development', 'AUTH_DIAGNOSTICS': 'true'}):
                with self.assertLogs('uvicorn.error', level='WARNING') as logs:
                    with self.assertRaises(InvalidMembership): user_from_claims(claims)
            output = ' '.join(logs.output)
            self.assertIn('reason=' + reason, output)
            self.assertNotIn(sentinel, output)
        for env in [{'APP_ENV': 'production', 'AUTH_DIAGNOSTICS': 'true'}, {'APP_ENV': 'development', 'AUTH_DIAGNOSTICS': 'false'}, {'APP_ENV': '', 'AUTH_DIAGNOSTICS': 'true'}]:
            with patch.dict('os.environ', env), patch('app.auth.logger.warning') as log:
                self.verifier.verify(self.token())
                log.assert_not_called()
        with patch.dict('os.environ', {'APP_ENV': 'development', 'AUTH_DIAGNOSTICS': 'true'}), patch('app.auth.logger.warning') as log:
            with self.assertRaises(InvalidAuthentication): self.verifier.verify('not-a-jwt')
            log.assert_not_called()

    def test_invalid_claim_context_and_signature(self):
        for changes in [{'exp': int(time.time()) - 1}, {'iss': 'https://untrusted.invalid'}, {'aud': 'wrong-client'}, {'token_use': 'access'}, {'iat': int(time.time()) + 300}]:
            with self.subTest(changes=changes), self.assertRaises(InvalidAuthentication):
                self.verifier.verify(self.token(self.claims(**changes)))
        with self.assertRaises(InvalidAuthentication):
            self.verifier.verify(self.token(key=self.other))
        for missing in ['exp', 'iat', 'sub', 'aud', 'token_use']:
            claims = self.claims(); claims.pop(missing)
            with self.subTest(missing=missing), self.assertRaises(InvalidAuthentication):
                self.verifier.verify(self.token(claims))

    def test_malformed_and_wrong_algorithm_rejected_before_key_lookup(self):
        for token in ['not-a-token', jwt.encode(self.claims(), 'test-only-hmac-key-that-is-long-enough', algorithm='HS256', headers={'kid': 'test'})]:
            with self.assertRaises(InvalidAuthentication):
                self.verifier.verify(token)
        self.keys.get_signing_key_from_jwt.assert_not_called()

    def test_missing_business_and_unrecognized_groups(self):
        for changes in [{'custom:business_id': ''}, {'custom:business_id': 'bad/business'}, {'cognito:groups': []}, {'cognito:groups': ['Unrecognized']}, {'cognito:groups': 'Owner'}]:
            with self.subTest(changes=changes), self.assertRaises(InvalidMembership):
                self.verifier.verify(self.token(self.claims(**changes)))
        claims = self.claims(); claims.pop('custom:business_id')
        with self.assertRaises(InvalidMembership):
            self.verifier.verify(self.token(claims))

    def test_unknown_key_and_jwks_network_failure_fail_closed(self):
        from app.auth import AuthenticationUnavailable
        self.keys.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientError('unknown key')
        with self.assertRaises(InvalidAuthentication): self.verifier.verify(self.token())
        self.keys.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError('test network')
        with self.assertRaises(AuthenticationUnavailable): self.verifier.verify(self.token())
        with self.assertRaises(AuthenticationUnavailable): CognitoVerifier('', '', 'eu-west-1').verify('anything')


class AuthorizationAPITests(unittest.TestCase):
    def setUp(self):
        with patch('app.config.build_repository'), patch('app.media_storage.build_media_storage'):
            from main import create_app
        self.repo = InMemoryCustomerRepository()
        self.verifier = Mock()
        self.app = create_app(self.repo, self.verifier)
        self.user = UserContext('fixture-user', None, 'tenant-a', ('Owner',), Role.OWNER)
        self.verifier.verify.return_value = self.user
        self.payload = {'first_name': 'Fictional', 'last_name': 'Customer', 'phone': '0871234567', 'date_of_birth': '1990-01-01'}

    def call(self, **kwargs):
        return asyncio.run(request(self.app, **kwargs))

    def test_all_customer_endpoints_require_authentication(self):
        for method, path, data in [('GET', '/customers', None), ('POST', '/customers', self.payload), ('GET', '/customers/id', None), ('PUT', '/customers/id', self.payload)]:
            self.assertEqual(self.call(method=method, path=path, data=data)[0], 401)
        self.verifier.verify.assert_not_called()

    def test_each_role_can_create_list_view_edit(self):
        for role in Role:
            with self.subTest(role=role):
                self.verifier.verify.return_value = UserContext('fixture-user', None, role.value, (role.value.title(),), role)
                status, customer = self.call(method='POST', token='fixture', data=self.payload)
                self.assertEqual(status, 201)
                path = '/customers/' + customer['customer_id']
                self.assertEqual(customer['business_id'], role.value)
                self.assertEqual(self.call(token='fixture')[0], 200)
                self.assertEqual(self.call(path=path, token='fixture')[0], 200)
                self.assertEqual(self.call(method='PUT', path=path, token='fixture', data={**self.payload, 'first_name': 'Updated'})[1]['first_name'], 'Updated')

    def test_frontend_business_cannot_select_another_tenant(self):
        self.assertEqual(self.call(token='fixture', query='business_id=tenant-b')[0], 403)
        self.assertEqual(self.call(method='POST', token='fixture', data={**self.payload, 'business_id': 'tenant-b'})[0], 422)
        status, customer = self.call(method='POST', token='fixture', data=self.payload)
        self.assertEqual(status, 201)
        self.verifier.verify.return_value = UserContext('other-user', None, 'tenant-b', ('Owner',), Role.OWNER)
        self.assertEqual(self.call(token='fixture')[1], [])
        self.assertEqual(self.call(token='fixture', path='/customers/' + customer['customer_id'])[0], 404)
        self.assertEqual(self.call(method='PUT', token='fixture', path='/customers/' + customer['customer_id'], data=self.payload)[0], 404)

    def test_verification_errors_are_safe(self):
        for error, status in [(InvalidAuthentication('private'), 401), (InvalidMembership('private'), 403)]:
            self.verifier.verify.side_effect = error
            result, body = self.call(token='fixture')
            self.assertEqual(result, status)
            self.assertNotIn('private', json.dumps(body))

    def test_staff_cannot_deactivate_but_manager_can(self):
        _, customer = self.call(method='POST', token='fixture', data=self.payload)
        self.verifier.verify.return_value = UserContext('staff', None, 'tenant-a', ('Staff',), Role.STAFF)
        path = '/customers/' + customer['customer_id']
        self.assertEqual(self.call(method='PUT', path=path, token='fixture', data={**self.payload, 'status': 'inactive'})[0], 403)
        self.verifier.verify.return_value = UserContext('manager', None, 'tenant-a', ('Manager',), Role.MANAGER)
        self.assertEqual(self.call(method='PUT', path=path, token='fixture', data={**self.payload, 'status': 'inactive'})[0], 200)

    def test_staff_edit_cannot_reactivate_during_concurrent_deactivation(self):
        _, customer = self.call(method='POST', token='fixture', data=self.payload)
        self.verifier.verify.return_value = UserContext('staff', None, 'tenant-a', ('Staff',), Role.STAFF)
        original = self.app.state.customer_service.update
        def race(*args, **kwargs):
            # Simulate a manager write after the route authorized the active snapshot.
            from app.models import CustomerInput
            original('tenant-a', customer['customer_id'], CustomerInput(**{**self.payload, 'status': 'inactive'}))
            return original(*args, **kwargs)
        with patch.object(self.app.state.customer_service, 'update', side_effect=race):
            self.assertEqual(self.call(method='PUT', token='fixture', path='/customers/' + customer['customer_id'], data=self.payload)[0], 409)
        self.assertEqual(self.repo.get('tenant-a', customer['customer_id']).status, 'inactive')

    def test_reusable_owner_and_document_guards(self):
        from fastapi import HTTPException
        owner = self.user
        staff = UserContext('staff', None, 'tenant-a', ('Staff',), Role.STAFF)
        manager = UserContext('manager', None, 'tenant-a', ('Manager',), Role.MANAGER)
        self.assertEqual(require_owner(owner), owner)
        self.assertEqual(require_management(manager), manager)
        with self.assertRaises(HTTPException): require_owner(manager)
        with self.assertRaises(HTTPException): require_management(staff)
