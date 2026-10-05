import json
import os
import socket
import subprocess
import sys
import time
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, urlsplit


class CustomerAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.base = f'http://127.0.0.1:{port}'
        cls.server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'auth_test_server:app', '--app-dir', 'tests', '--host', '127.0.0.1', '--port', str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, 'CUSTOMER_REPOSITORY': 'memory', 'S3_DOCUMENTS_BUCKET': ''})
        for _ in range(100):
            try:
                urlopen(cls.base + '/health', timeout=1).close()
                return
            except URLError:
                time.sleep(.05)
        cls.server.terminate()
        raise RuntimeError('Test API failed to start')

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=5)

    def request(self, method, path, data=None):
        req = Request(self.base + path, data=json.dumps(data).encode() if data is not None else None, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer fixture:' + parse_qs(urlsplit(path).query).get('business_id', ['trumps'])[0]}, method=method)
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def payload(self, **changes):
        return {'first_name': 'Ada', 'last_name': 'Lovelace', 'phone': '+353871234567', 'date_of_birth': '1990-12-10', **changes}

    def test_crud_and_consent(self):
        path = '/customers?business_id=crud'
        status, c = self.request('POST', path, self.payload(marketing_consent=True))
        self.assertEqual(status, 201)
        self.assertNotEqual(c['customer_id'], c['qr_token'])
        self.assertGreaterEqual(len(c['qr_token']), 40)
        self.assertTrue(c['created_at'].endswith('Z'))
        self.assertIsNotNone(c['consent_timestamp'])
        detail = f"/customers/{c['customer_id']}?business_id=crud"
        self.assertEqual(self.request('GET', detail), (200, c))
        self.assertEqual(len(self.request('GET', path)[1]), 1)
        status, edited = self.request('PUT', detail, self.payload(first_name='Grace', marketing_consent=True))
        self.assertEqual(status, 200)
        for field in ['customer_id', 'qr_token', 'created_at', 'consent_timestamp']:
            self.assertEqual(c[field], edited[field])
        status, revoked = self.request('PUT', detail, self.payload(marketing_consent=False, status='inactive'))
        self.assertEqual(status, 200)
        self.assertFalse(revoked['marketing_consent'])
        self.assertNotEqual(revoked['consent_timestamp'], c['consent_timestamp'])

    def test_business_isolation_and_duplicates(self):
        self.assertEqual(self.request('POST', '/customers?business_id=one', self.payload())[0], 201)
        self.assertEqual(self.request('POST', '/customers?business_id=one', self.payload(phone='+353 (87) 123-4567'))[0], 409)
        status, other = self.request('POST', '/customers?business_id=two', self.payload())
        self.assertEqual(status, 201)
        self.assertEqual(self.request('GET', f"/customers/{other['customer_id']}?business_id=one")[0], 404)
        self.assertEqual(self.request('PUT', '/customers/missing', self.payload())[0], 404)
        _, second = self.request('POST', '/customers?business_id=one', self.payload(phone='+353871234568'))
        self.assertEqual(self.request('PUT', f"/customers/{second['customer_id']}?business_id=one", self.payload())[0], 409)
        self.assertEqual(self.request('GET', f"/customers/{second['customer_id']}?business_id=one")[1]['phone'], '+353871234568')

    def test_validation(self):
        for changes in [{'first_name': '  '}, {'phone': '123'}, {'date_of_birth': '2999-01-01'}, {'date_of_birth': 'no'}, {'email': 'invalid'}, {'status': 'unknown'}, {'qr_token': 'injected'}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.request('POST', '/customers', self.payload(**changes))[0], 422)
        self.assertEqual(self.request('POST', '/customers', {})[0], 422)
        self.assertEqual(self.request('GET', '/customers?business_id=')[0], 403)

    def test_irish_mobile_normalization(self):
        for business, phone in [('national', '0871234567'), ('international', '+353871234567'), ('formatted', '087 123 4567')]:
            with self.subTest(phone=phone):
                status, customer = self.request('POST', f'/customers?business_id={business}', self.payload(phone=phone))
                self.assertEqual(status, 201)
                self.assertEqual(customer['phone'], '+353871234567')
                self.assertEqual(self.request('GET', f"/customers/{customer['customer_id']}?business_id={business}")[1]['phone'], '+353871234567')
        self.assertEqual(self.request('POST', '/customers?business_id=national', self.payload(phone='+353871234567'))[0], 409)
        self.assertEqual(self.request('POST', '/customers?business_id=international', self.payload(phone='0871234567'))[0], 409)
        for prefix in ['083', '085', '086', '087', '089']:
            self.assertEqual(self.request('POST', f'/customers?business_id=prefix{prefix}', self.payload(phone=prefix + '7654321'))[0], 201)

    def test_invalid_irish_mobiles(self):
        for phone in ['087', '087123456', '08712345678', '+35387123456', '+3530871234567', '087abcdefg', '0871234567!', '+44871234567', '0811234567', '0881234567', '871234567', '087123/4567']:
            with self.subTest(phone=phone):
                status, body = self.request('POST', '/customers', self.payload(phone=phone))
                self.assertEqual(status, 422)
                self.assertIn('valid Irish mobile number', body['detail'][0]['msg'])

    def test_minimum_age_calendar_boundaries(self):
        today = datetime.now(ZoneInfo('Europe/Dublin')).date()
        # Feb 29 becomes March 1 eighteen years ago, so it is still underage today.
        try:
            eighteenth = today.replace(year=today.year - 18)
        except ValueError:
            eighteenth = today.replace(year=today.year - 18, month=2, day=28)
        status, _ = self.request('POST', '/customers?business_id=adult', self.payload(date_of_birth=eighteenth.isoformat()))
        self.assertEqual(status, 201)
        underage = eighteenth + timedelta(days=1)
        status, body = self.request('POST', '/customers?business_id=underage', self.payload(date_of_birth=underage.isoformat()))
        self.assertEqual(status, 422)
        self.assertIn('Customer must be at least 18 years old.', body['detail'][0]['msg'])
        self.assertEqual(self.request('GET', '/customers?business_id=underage')[1], [])
        status, body = self.request('POST', '/customers', self.payload(date_of_birth=(today + timedelta(days=1)).isoformat()))
        self.assertEqual(status, 422)
        self.assertIn('future', body['detail'][0]['msg'])
        self.assertEqual(self.request('POST', '/customers', self.payload(date_of_birth='2000-02-30'))[0], 422)

    def test_update_validation_and_normalization(self):
        _, customer = self.request('POST', '/customers?business_id=updates', self.payload())
        path = f"/customers/{customer['customer_id']}?business_id=updates"
        status, updated = self.request('PUT', path, self.payload(phone='087 765 4321'))
        self.assertEqual(status, 200)
        self.assertEqual(updated['phone'], '+353877654321')
        self.assertEqual(self.request('PUT', path, self.payload(phone='087123'))[0], 422)
        self.assertEqual(self.request('PUT', path, self.payload(date_of_birth='2020-01-01'))[0], 422)
        self.assertEqual(self.request('GET', path)[1], updated)

    def test_concurrent_duplicate_creation(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda _: self.request('POST', '/customers?business_id=race', self.payload())[0], range(2)))
        self.assertEqual(sorted(statuses), [201, 409])


if __name__ == '__main__':
    unittest.main()
