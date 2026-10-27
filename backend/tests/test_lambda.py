"""Offline HTTP API v2 adapter tests: no AWS, JWTs, SMS or printer output."""
import asyncio
import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from mangum import Mangum
from app.application import create_app
from app.auth import Role, UserContext
from app.repository import InMemoryCustomerRepository
from app.media_storage import UnconfiguredMediaStorage
from app.sms_worker import SMSWorker


def event(path='/health', method='GET', body=None, token=None, query='', encoded=False):
    headers = {'host': 'fixture.execute-api.eu-west-1.amazonaws.com', 'content-type': 'application/json', 'x-forwarded-proto': 'https'}
    if token is not None: headers['authorization'] = 'Bearer ' + token
    payload = json.dumps(body) if body is not None else ''
    if encoded: payload = base64.b64encode(payload.encode()).decode()
    return {'version': '2.0', 'routeKey': '$default', 'rawPath': path, 'rawQueryString': query,
            'headers': headers, 'body': payload, 'isBase64Encoded': encoded,
            'requestContext': {'stage': '$default', 'requestId': 'fixture-request',
                'http': {'method': method, 'path': path, 'protocol': 'HTTP/1.1', 'sourceIp': '127.0.0.1', 'userAgent': 'fixture'},
                'domainName': 'fixture.execute-api.eu-west-1.amazonaws.com'}}


class LambdaTests(unittest.TestCase):
    def setUp(self):
        # Mangum uses a synchronous event loop; do not leak it between test cases.
        self.loop = asyncio.new_event_loop(); asyncio.set_event_loop(self.loop)
        self.repo = InMemoryCustomerRepository(); self.verifier = Mock()
        self.user = UserContext('fixture-owner', None, 'tenant-a', (), Role.OWNER)
        self.verifier.verify.return_value = self.user
        self.app = create_app(self.repo, self.verifier, UnconfiguredMediaStorage(), start_sms_worker=False)
        self.handler = Mangum(self.app, lifespan='off')
        self.payload = {'first_name': 'Fictional', 'last_name': 'Customer', 'phone': '0871234567', 'date_of_birth': '1990-01-01', 'marketing_consent': True}

    def tearDown(self):
        self.loop.run_until_complete(self.loop.shutdown_asyncgens())
        self.loop.run_until_complete(self.loop.shutdown_default_executor())
        self.loop.close(); asyncio.set_event_loop(None)

    def invoke(self, *args, **kwargs):
        return self.handler(event(*args, **kwargs), SimpleNamespace(aws_request_id='fixture-context'))

    def test_http_api_health_and_warm_repeated_requests(self):
        with patch.object(self.app.state.sms_worker, 'start') as start, patch.object(self.app.state.sms_worker, 'stop') as stop:
            for _ in range(3):
                response = self.invoke()
                self.assertEqual(response['statusCode'], 200)
                self.assertEqual(json.loads(response['body']), {'status': 'healthy'})
                self.assertFalse(response.get('isBase64Encoded', False))
            start.assert_not_called(); stop.assert_not_called()
        self.assertIsNone(self.app.state.sms_worker.thread)

    def test_authenticated_customer_post_and_read_via_real_adapter(self):
        response = self.invoke('/customers', 'POST', self.payload, 'fixture', encoded=True)
        self.assertEqual(response['statusCode'], 201)
        customer = json.loads(response['body'])
        self.assertEqual(customer['business_id'], 'tenant-a'); self.assertEqual(customer['phone'], '+353871234567')
        response = self.invoke('/customers/' + customer['customer_id'], token='fixture')
        self.assertEqual(response['statusCode'], 200)
        self.verifier.verify.assert_called_with('fixture')

    def test_gateway_claims_do_not_bypass_backend_authentication(self):
        request = event('/auth/me')
        request['requestContext']['authorizer'] = {'jwt': {'claims': {'custom:business_id': 'tenant-a', 'role': 'OWNER'}}}
        self.assertEqual(self.handler(request, None)['statusCode'], 401)
        self.verifier.verify.assert_not_called()
        self.assertEqual(self.invoke('/customers')['statusCode'], 401)

    def test_tenant_scope_and_management_permissions_remain_enforced(self):
        created = json.loads(self.invoke('/customers', 'POST', self.payload, 'fixture')['body'])
        self.assertEqual(self.invoke('/customers', token='fixture', query='business_id=tenant-b')['statusCode'], 403)
        self.verifier.verify.return_value = UserContext('other', None, 'tenant-b', (), Role.OWNER)
        self.assertEqual(self.invoke('/customers/' + created['customer_id'], token='fixture')['statusCode'], 404)
        self.verifier.verify.return_value = UserContext('staff', None, 'tenant-a', (), Role.STAFF)
        self.assertEqual(self.invoke('/sms/history', token='fixture')['statusCode'], 403)

    def test_sms_confirmation_does_not_start_or_process_background_worker(self):
        customer = json.loads(self.invoke('/customers', 'POST', self.payload, 'fixture')['body'])
        with patch.object(self.app.state.sms_worker, 'start') as start, patch.object(self.app.state.sms_service, 'process') as process:
            draft = json.loads(self.invoke('/sms/preview', 'POST', {'audience': 'individual', 'customer_id': customer['customer_id'], 'message': 'Fictional test message'}, 'fixture')['body'])
            response = self.invoke('/sms/campaigns/' + draft['campaign_id'] + '/confirm', 'POST', {'confirmed': True}, 'fixture')
            self.assertEqual(response['statusCode'], 200)
            self.assertEqual(json.loads(response['body'])['recipients'][0]['status'], 'QUEUED')
            self.assertEqual(self.app.state.sms_worker.businesses, {'tenant-a'})
            start.assert_not_called(); process.assert_not_called()
        self.assertIsNone(self.app.state.sms_worker.thread)

    def test_lambda_app_lifespan_cannot_start_thread_even_when_entered(self):
        async def lifecycle():
            async with self.app.router.lifespan_context(self.app): pass
        with patch.object(self.app.state.sms_worker, 'start') as start, patch.object(self.app.state.sms_worker, 'stop') as stop:
            self.loop.run_until_complete(lifecycle())
            start.assert_not_called(); stop.assert_not_called()

    def test_actual_lambda_module_initializes_once_without_background_work(self):
        spec = importlib.util.spec_from_file_location('fixture_lambda_entry', Path(__file__).parents[1] / 'lambda_function.py')
        module = importlib.util.module_from_spec(spec)
        def factory(**kwargs):
            return create_app(self.repo, self.verifier, UnconfiguredMediaStorage(), **kwargs)
        with patch('app.application.create_app', side_effect=factory) as create, patch.object(SMSWorker, 'start') as start, patch.object(SMSWorker, 'stop') as stop:
            spec.loader.exec_module(module)
            create.assert_called_once_with(start_sms_worker=False)
            self.assertFalse(module.app.state.sms_worker_enabled)
            self.assertEqual(module.handler.lifespan, 'off')
            for _ in range(2): self.assertEqual(module.handler(event(), None)['statusCode'], 200)
            self.assertEqual(create.call_count, 1)
            start.assert_not_called(); stop.assert_not_called()
        self.assertIsNone(module.app.state.sms_worker.thread)

    def test_local_default_app_starts_and_stops_simulation_worker(self):
        app = create_app(self.repo, self.verifier, UnconfiguredMediaStorage())
        async def lifecycle():
            async with app.router.lifespan_context(app):
                self.assertTrue(app.state.sms_worker.thread.is_alive())
            self.assertFalse(app.state.sms_worker.thread.is_alive())
        self.assertTrue(app.state.sms_worker_enabled)
        self.loop.run_until_complete(lifecycle())

    def test_uvicorn_import_target_is_still_local_app(self):
        from uvicorn import Config
        config = Config('main:app', lifespan='on')
        with patch('app.config.build_repository', return_value=self.repo), patch('app.media_storage.build_media_storage', return_value=UnconfiguredMediaStorage()):
            config.load()
        import main
        self.assertTrue(main.app.state.sms_worker_enabled)
        self.assertTrue(config.loaded)
