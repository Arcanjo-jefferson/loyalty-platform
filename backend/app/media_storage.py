"""Private S3 adapter; keys are created and authorized only by the service."""
from typing import Protocol
from botocore.exceptions import BotoCoreError, ClientError

MAX_IMAGE_BYTES = 5 * 1024 * 1024


class MediaUnavailable(Exception):
    pass


class MediaStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class S3MediaStorage:
    def __init__(self, client, bucket):
        self.client, self.bucket = client, bucket

    def put(self, key, data, content_type):
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data,
                                   ContentType=content_type, ServerSideEncryption='AES256',
                                   CacheControl='no-store', IfNoneMatch='*')
        except (ClientError, BotoCoreError) as exc:
            raise MediaUnavailable() from exc

    def get(self, key):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            body = response['Body']
            try:
                data = body.read(MAX_IMAGE_BYTES + 1)
            finally:
                body.close()
            if len(data) > MAX_IMAGE_BYTES:
                raise MediaUnavailable()
            return data
        except (ClientError, BotoCoreError, OSError, KeyError) as exc:
            raise MediaUnavailable() from exc

    def delete(self, key):
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise MediaUnavailable() from exc


class UnconfiguredMediaStorage:
    def put(self, *args): raise MediaUnavailable()
    def get(self, *args): raise MediaUnavailable()
    def delete(self, *args): raise MediaUnavailable()


def build_media_storage():
    # Loaded after Settings reads backend/.env; no bucket changes or credentials.
    import os
    import boto3
    from botocore.config import Config
    bucket = os.getenv('S3_DOCUMENTS_BUCKET', '').strip()
    if not bucket:
        return UnconfiguredMediaStorage()
    try:
        session = boto3.Session(profile_name=os.getenv('AWS_PROFILE', '').strip() or None,
                                region_name=os.getenv('S3_REGION', os.getenv('AWS_REGION', 'eu-west-1')))
        client = session.client('s3', config=Config(retries={'mode': 'standard', 'total_max_attempts': 3}, connect_timeout=3, read_timeout=10))
        return S3MediaStorage(client, bucket)
    except BotoCoreError:
        return UnconfiguredMediaStorage()
