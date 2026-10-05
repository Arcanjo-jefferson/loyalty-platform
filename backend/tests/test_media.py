import asyncio
from copy import deepcopy
from io import BytesIO
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PIL import Image, PngImagePlugin
from botocore.exceptions import ClientError
from botocore.stub import Stubber, ANY
import boto3
from app.auth import Role, UserContext
from app.models import CustomerInput
from app.repository import InMemoryCustomerRepository, ConcurrentModification, StorageUnavailable
from app.dynamodb_repository import DynamoDBCustomerRepository
from app.service import CustomerService
from app.media_service import MediaService, validated_image, InvalidImage, ImageTooLarge
from app.media_storage import MAX_IMAGE_BYTES, S3MediaStorage, MediaUnavailable, build_media_storage
from fake_dynamodb import FakeDynamoDB


def image_bytes(format='PNG'):
    output = BytesIO(); Image.new('RGB', (12, 8), 'red').save(output, format=format); return output.getvalue()


class FakeS3:
    def __init__(self):
        self.objects = {}; self.calls = []; self.fail_delete = False; self.fail_put = False
    def put(self, key, data, content_type):
        self.calls.append(('put', key))
        if self.fail_put: raise MediaUnavailable()
        self.objects[key] = data
    def get(self, key): return self.objects[key]
    def delete(self, key):
        self.calls.append(('delete', key))
        if self.fail_delete: raise MediaUnavailable()
        self.objects.pop(key, None)


async def request(app, method, path, token='fixture', body=b'', content_type='image/png', query=''):
    messages = []
    async def receive(): return {'type': 'http.request', 'body': body, 'more_body': False}
    async def send(message): messages.append(message)
    headers = [(b'content-type', content_type.encode())]
    if token: headers.append((b'authorization', ('Bearer ' + token).encode()))
    await app({'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(), 'query_string': query.encode(), 'headers': headers, 'server': ('test', 80), 'client': ('test', 1)}, receive, send)
    start = next(m for m in messages if m['type'] == 'http.response.start')
    raw = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
    return start['status'], raw, dict(start['headers'])


class MediaAPITests(unittest.TestCase):
    def setUp(self):
        with patch('app.config.build_repository'), patch('app.media_storage.build_media_storage'):
            from main import create_app
        self.repo = InMemoryCustomerRepository(); self.s3 = FakeS3(); self.verifier = Mock()
        self.user = UserContext('fixture-user', None, 'tenant-a', ('owner',), Role.OWNER)
        self.verifier.verify.return_value = self.user
        self.app = create_app(self.repo, self.verifier, self.s3)
        self.customer = self.app.state.customer_service.create('tenant-a', CustomerInput(first_name='Fictional', last_name='Only', phone='0871234567', date_of_birth='1990-01-01', marketing_consent=True))
        self.base = '/customers/' + self.customer.customer_id
    def call(self, method='GET', suffix='/profile-photo', **kwargs):
        return asyncio.run(request(self.app, method, self.base + suffix, **kwargs))
    def upload(self, kind='profile-photo'):
        status, raw, _ = self.call('POST', '/' + kind, body=image_bytes(), query='document_type=Passport' if kind == 'id-document' else '')
        self.assertEqual(status, 201); return json.loads(raw)

    def test_unauthenticated_media_endpoints_rejected(self):
        for kind in ['profile-photo', 'id-document', 'consent-evidence']:
            for method, suffix in [('POST', '/' + kind), ('GET', '/' + kind), ('GET', '/' + kind + '/image')]:
                self.assertEqual(self.call(method, suffix, token=None)[0], 401)
        self.assertEqual(self.call('PATCH', '/id-document/verification', token=None, body=b'{}', content_type='application/json')[0], 401)
        self.assertEqual(self.s3.calls, [])

    def test_all_roles_profile_and_management_document_permissions(self):
        for role in Role:
            self.verifier.verify.return_value = UserContext('test-subject', None, 'tenant-a', (), role)
            metadata = self.upload()
            status, raw, headers = self.call(suffix='/profile-photo/image')
            self.assertEqual(status, 200); self.assertTrue(raw.startswith(b'\x89PNG'))
            self.assertEqual(headers[b'cache-control'], b'no-store, private')
            self.assertEqual(headers[b'x-content-type-options'], b'nosniff')
            self.assertEqual(self.call()[0], 200)
            for kind in ['id-document', 'consent-evidence']:
                if role != Role.STAFF:
                    self.upload(kind)
                    self.assertEqual(self.call(suffix='/' + kind)[0], 200)
                    self.assertEqual(self.call(suffix='/' + kind + '/image')[0], 200)
                else:
                    for method, suffix in [('POST', '/' + kind), ('GET', '/' + kind), ('GET', '/' + kind + '/image')]:
                        status, raw, _ = self.call(method, suffix, body=image_bytes())
                        self.assertEqual(status, 403)
                        self.assertNotIn(b'businesses/', raw)
                    body = json.dumps({'status': 'Verified', 'revision': metadata['revision']}).encode()
                    self.assertEqual(self.call('PATCH', '/id-document/verification', body=body, content_type='application/json')[0], 403)

    def test_tenant_isolation_and_untrusted_identifiers(self):
        self.upload('id-document')
        self.verifier.verify.return_value = UserContext('other', None, 'tenant-b', (), Role.OWNER)
        for method, suffix in [('POST', '/profile-photo'), ('GET', '/id-document'), ('GET', '/id-document/image')]:
            self.assertEqual(self.call(method, suffix, body=image_bytes(), query='business_id=tenant-a')[0], 403)
            self.assertEqual(self.call(method, suffix, body=image_bytes())[0], 404)
        self.verifier.verify.return_value = self.user
        for query in ['key=businesses/other', 'role=Owner', 'customer_id=other']:
            self.assertEqual(self.call('POST', body=image_bytes(), query=query)[0], 422)
        status, raw, _ = self.call(suffix='/id-document/image', query='key=other')
        self.assertEqual(status, 200)  # Ignored; always resolves the authorized stored reference.
        self.assertEqual(len(self.s3.objects), 1)

    def test_file_type_size_and_corruption_rejected(self):
        self.assertEqual(self.call('POST', body=b'<svg/>', content_type='image/svg+xml')[0], 415)
        self.assertEqual(self.call('POST', body=b'not an image')[0], 422)
        self.assertEqual(self.call('POST', body=image_bytes('JPEG'))[0], 422)
        self.assertEqual(self.call('POST', body=b'x' * (MAX_IMAGE_BYTES + 1))[0], 413)
        self.assertEqual(self.call('POST', '/id-document', body=image_bytes(), query='document_type=Unrecognized')[0], 422)
        self.assertEqual(self.s3.calls, [])

    def test_id_verification_rejection_replacement_and_stale_version(self):
        metadata = self.upload('id-document'); self.assertEqual(metadata['verification_status'], 'Pending')
        for role, status in [(Role.OWNER, 'Verified'), (Role.MANAGER, 'Rejected')]:
            self.verifier.verify.return_value = UserContext('verifier-subject', None, 'tenant-a', (), role)
            body = json.dumps({'revision': metadata['revision'], 'status': status}).encode()
            code, raw, _ = self.call('PATCH', '/id-document/verification', body=body, content_type='application/json')
            self.assertEqual(code, 200); metadata = json.loads(raw)
            self.assertEqual(metadata['verification_status'], status)
            self.assertIsNotNone(metadata['verified_at'])
            stored = self.repo.get_media('tenant-a', self.customer.customer_id, 'identity')
            self.assertEqual(stored['verified_by'], 'verifier-subject')
        before = metadata['revision']; metadata = self.upload('id-document')
        self.assertEqual(metadata['verification_status'], 'Pending'); self.assertIsNone(metadata['verified_at'])
        body = json.dumps({'revision': before, 'status': 'Verified'}).encode()
        self.assertEqual(self.call('PATCH', '/id-document/verification', body=body, content_type='application/json')[0], 409)
        self.assertEqual(self.call(suffix='/id-document/image', query='revision=' + before)[0], 409)

    def test_consent_evidence_keeps_consent_and_private_audit_metadata(self):
        metadata = self.upload('consent-evidence')
        self.assertEqual(metadata['evidence_type'], 'signed_marketing_consent')
        self.assertEqual(metadata['related_consent_timestamp'], self.customer.consent_timestamp.isoformat())
        stored = self.repo.get_media('tenant-a', self.customer.customer_id, 'consent')
        self.assertEqual(stored['uploaded_by'], self.user.subject)
        self.assertEqual(self.repo.get('tenant-a', self.customer.customer_id), self.customer)
        for suffix in ['/consent-evidence', '']:
            status, raw, _ = self.call(suffix=suffix)
            self.assertEqual(status, 200)
            for private in [b'key', b'uploaded_by', b'fixture-user', b'businesses/', b'cleanup_keys']:
                self.assertNotIn(private, raw)
        status, raw, _ = asyncio.run(request(self.app, 'GET', '/customers'))
        self.assertEqual(status, 200); self.assertNotIn(b'evidence_type', raw)

    def test_dynamodb_media_numeric_metadata_is_json_serializable(self):
        repo = DynamoDBCustomerRepository(FakeDynamoDB(), 'fixture-table')
        repo.save(self.customer)
        self.repo = repo
        self.app.state.customer_service = CustomerService(repo)
        self.app.state.media_service = MediaService(self.app.state.customer_service, self.s3)
        result = self.upload('id-document')
        code, raw, _ = self.call(suffix='/id-document')
        self.assertEqual(code, 200)
        self.assertIsInstance(json.loads(raw)['size_bytes'], int)
        body = json.dumps({'revision': result['revision'], 'status': 'Verified'}).encode()
        self.assertEqual(self.call('PATCH', '/id-document/verification', body=body, content_type='application/json')[0], 200)

    def test_s3_errors_safe_and_no_false_upload_success(self):
        self.s3.fail_put = True
        code, raw, _ = self.call('POST', body=image_bytes())
        self.assertEqual(code, 503); self.assertNotIn(b'key', raw)
        self.assertIsNone(self.repo.get_media('tenant-a', self.customer.customer_id, 'profile'))


class MediaServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDynamoDB(); self.repo = DynamoDBCustomerRepository(self.db, 'fixture-table')
        self.customers = CustomerService(self.repo); self.s3 = FakeS3(); self.service = MediaService(self.customers, self.s3)
        self.user = UserContext('fictional-subject', None, 'trumps', (), Role.OWNER)
        self.customer = self.customers.create('trumps', CustomerInput(first_name='Fictional', last_name='Only', phone='0871234567', date_of_birth='1990-01-01'))
    def upload(self): return self.service.upload(self.user, self.customer.customer_id, 'profile-photo', image_bytes(), 'image/png')

    def test_dynamodb_metadata_preserved_by_customer_and_phone_updates(self):
        saved = self.upload()
        self.customers.update('trumps', self.customer.customer_id, CustomerInput(first_name='Changed', last_name='Only', phone='0851234567', date_of_birth='1990-01-01'))
        metadata = self.repo.get_media('trumps', self.customer.customer_id, 'profile')
        self.assertEqual(metadata['revision'], saved['revision'])
        self.assertEqual(len(self.repo.list('trumps')), 1)
        self.assertNotIn('media_profile', self.repo.list('trumps')[0].model_dump())
        self.assertTrue(any(key[1].startswith('PHONE#') for key in self.db.items))
        self.assertFalse(any(call[0] == 'scan' for call in self.db.calls))

    def test_server_keys_are_scoped_random_and_have_no_customer_pii(self):
        self.upload(); key = next(iter(self.s3.objects))
        self.assertRegex(key, '^businesses/trumps/customers/' + self.customer.customer_id + '/profile/[a-f0-9]{32}.png$')
        for pii in ['Fictional', 'Only', '871234567', '1990']: self.assertNotIn(pii, key)

    def test_replacement_deletes_old_only_after_metadata_commit(self):
        first = self.upload(); old_key = next(iter(self.s3.objects))
        original = self.repo.save_media
        def save(*args, **kwargs):
            if args[3].get('cleanup_keys'): self.assertIn(old_key, self.s3.objects)
            return original(*args, **kwargs)
        with patch.object(self.repo, 'save_media', side_effect=save):
            second = self.upload()
        self.assertNotEqual(first['revision'], second['revision']); self.assertNotIn(old_key, self.s3.objects)
        self.assertEqual(len(self.s3.objects), 1)

    def test_failed_conditional_write_discards_new_and_preserves_old(self):
        first = self.upload(); old = deepcopy(self.s3.objects)
        with patch.object(self.repo, 'save_media', side_effect=ConcurrentModification):
            with self.assertRaises(ConcurrentModification): self.upload()
        self.assertEqual(self.s3.objects, old)
        self.assertEqual(self.repo.get_media('trumps', self.customer.customer_id, 'profile')['revision'], first['revision'])

    def test_cleanup_failure_retains_reference_and_retries_on_next_replacement(self):
        self.upload(); old = next(iter(self.s3.objects)); self.s3.fail_delete = True
        with self.assertLogs('uvicorn.error', level='WARNING'): result = self.upload()
        self.assertTrue(result['cleanup_pending'])
        self.assertIn(old, self.repo.get_media('trumps', self.customer.customer_id, 'profile')['cleanup_keys'])
        self.s3.fail_delete = False; self.upload(); self.assertEqual(len(self.s3.objects), 1)

    def test_ambiguous_metadata_commit_is_reconciled_without_deleting_current_image(self):
        original = self.repo.save_media
        def save(*args, **kwargs):
            original(*args, **kwargs)
            raise StorageUnavailable()
        with patch.object(self.repo, 'save_media', side_effect=save): result = self.upload()
        metadata = self.repo.get_media('trumps', self.customer.customer_id, 'profile')
        self.assertEqual(result['revision'], metadata['revision']); self.assertIn(metadata['key'], self.s3.objects)

    def test_corrupt_cross_tenant_reference_is_never_retrieved(self):
        self.upload(); record = self.db.items[('trumps', self.customer.customer_id)]
        record['media_profile']['key'] = 'businesses/other/customers/other/identity/file.png'
        with self.assertRaises(MediaUnavailable): self.service.image('trumps', self.customer.customer_id, 'profile-photo')

    def test_stale_repository_revision_and_lock_item_rejected(self):
        self.upload()
        with self.assertRaises(ConcurrentModification):
            self.repo.save_media('trumps', self.customer.customer_id, 'profile', {}, expected_revision='stale')
        with self.assertRaises(ConcurrentModification):
            self.repo.save_media('trumps', 'PHONE#' + self.customer.phone, 'profile', {}, expected_revision=None)


class ImageValidationTests(unittest.TestCase):
    def test_supported_formats_decode_and_strip_embedded_metadata(self):
        for format, type in [('JPEG', 'image/jpeg'), ('PNG', 'image/png'), ('WEBP', 'image/webp')]:
            result, suffix = validated_image(image_bytes(format), type)
            with Image.open(BytesIO(result)) as image: self.assertEqual(image.format, format)
        info = PngImagePlugin.PngInfo(); info.add_text('secret-test', 'private-fixture')
        buffer = BytesIO(); Image.new('RGB', (8, 8)).save(buffer, 'PNG', pnginfo=info)
        clean, _ = validated_image(buffer.getvalue(), 'image/png')
        self.assertNotIn(b'private-fixture', clean)
    def test_animated_and_large_pixel_count_rejected(self):
        output = BytesIO(); Image.new('RGB', (10, 10)).save(output, 'PNG', save_all=True, append_images=[Image.new('RGB', (10, 10), 'red')])
        with self.assertRaises(InvalidImage): validated_image(output.getvalue(), 'image/png')
        with patch('app.media_service.MAX_PIXELS', 10):
            with self.assertRaises(InvalidImage): validated_image(image_bytes(), 'image/png')
        with self.assertRaises(ImageTooLarge): validated_image(b'x' * (MAX_IMAGE_BYTES + 1), 'image/png')


class S3AdapterTests(unittest.TestCase):
    def test_private_encrypted_sdk_calls_and_safe_failures(self):
        client = boto3.client('s3', region_name='eu-west-1', aws_access_key_id='fixture', aws_secret_access_key='fixture')
        storage = S3MediaStorage(client, 'fixture-bucket')
        with Stubber(client) as stub:
            stub.add_response('put_object', {}, {'Bucket': 'fixture-bucket', 'Key': 'fixture-key', 'Body': b'image', 'ContentType': 'image/png', 'ServerSideEncryption': 'AES256', 'CacheControl': 'no-store', 'IfNoneMatch': '*'})
            stub.add_response('get_object', {'Body': BytesIO(b'image')}, {'Bucket': 'fixture-bucket', 'Key': 'fixture-key'})
            stub.add_response('delete_object', {}, {'Bucket': 'fixture-bucket', 'Key': 'fixture-key'})
            storage.put('fixture-key', b'image', 'image/png'); self.assertEqual(storage.get('fixture-key'), b'image'); storage.delete('fixture-key')
            stub.add_client_error('put_object', service_error_code='AccessDenied', service_message='private-detail')
            with self.assertRaises(MediaUnavailable): storage.put('fixture-key', b'image', 'image/png')
            stub.assert_no_pending_responses()
    def test_standard_credentials_and_optional_local_profile(self):
        for profile in ['', 'loyalty-dev']:
            with patch.dict('os.environ', {'S3_DOCUMENTS_BUCKET': 'fixture-bucket', 'S3_REGION': 'eu-west-1', 'AWS_PROFILE': profile}), patch('boto3.Session') as session:
                storage = build_media_storage()
                session.assert_called_once_with(profile_name=profile or None, region_name='eu-west-1')
                self.assertEqual(storage.bucket, 'fixture-bucket')
                session.return_value.client.assert_called_once()
                self.assertEqual(session.return_value.client.call_args.args[0], 's3')
    def test_dynamodb_sdk_accepts_conditional_media_attribute_updates(self):
        client = boto3.client('dynamodb', region_name='eu-west-1', aws_access_key_id='fixture', aws_secret_access_key='fixture')
        repo = DynamoDBCustomerRepository(client, 'fixture-table')
        with Stubber(client) as stub:
            stub.add_response('update_item', {}, {'TableName': 'fixture-table', 'Key': repo._key('tenant', 'customer'), 'UpdateExpression': 'SET #media = :media', 'ConditionExpression': '#type = :type AND attribute_not_exists(#media)', 'ExpressionAttributeNames': {'#media': 'media_profile', '#type': 'item_type'}, 'ExpressionAttributeValues': repo._encode({':media': {'revision': 'fixture'}, ':type': 'CUSTOMER'})})
            repo.save_media('tenant', 'customer', 'profile', {'revision': 'fixture'}, expected_revision=None)
            stub.assert_no_pending_responses()
