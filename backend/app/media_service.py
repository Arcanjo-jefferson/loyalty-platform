"""Tenant-scoped image validation, metadata, verification and replacement."""
import logging
import re
import warnings
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4
from PIL import Image, ImageOps, UnidentifiedImageError
from .media_storage import MAX_IMAGE_BYTES, MediaUnavailable
from .repository import ConcurrentModification, StorageUnavailable

FORMATS = {'image/jpeg': ('JPEG', 'jpg'), 'image/png': ('PNG', 'png'), 'image/webp': ('WEBP', 'webp')}
KINDS = {'profile-photo': 'profile', 'id-document': 'identity', 'consent-evidence': 'consent'}
DOCUMENT_TYPES = {'Passport', 'Driving Licence', 'National ID', 'Residence Permit', 'Other'}
MAX_PIXELS = 20_000_000
logger = logging.getLogger('uvicorn.error')


class InvalidImage(Exception):
    pass


class ImageTooLarge(Exception):
    pass


class MediaNotFound(Exception):
    pass


def validated_image(data, content_type):
    if len(data) > MAX_IMAGE_BYTES: raise ImageTooLarge()
    if content_type not in FORMATS: raise InvalidImage()
    expected, suffix = FORMATS[content_type]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data), formats=[expected]) as image:
                if image.format != expected or image.width * image.height > MAX_PIXELS or getattr(image, 'n_frames', 1) != 1:
                    raise InvalidImage()
                image.verify()
            with Image.open(BytesIO(data), formats=[expected]) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                # Fresh pixels preserve orientation but discard EXIF/GPS/ICC/text.
                clean = Image.new('RGB' if expected == 'JPEG' else 'RGBA', oriented.size)
                clean.paste(oriented.convert(clean.mode))
                output = BytesIO()
                clean.save(output, format=expected)
                encoded = output.getvalue()
                if len(encoded) > MAX_IMAGE_BYTES: raise ImageTooLarge()
                return encoded, suffix
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise InvalidImage() from exc


def public_metadata(metadata):
    # Exclude object keys, cleanup keys and Cognito subject identifiers.
    safe = {name: metadata[name] for name in ('revision', 'content_type', 'size_bytes', 'uploaded_at',
            'document_type', 'verification_status', 'verified_at', 'evidence_type', 'related_consent_timestamp') if name in metadata} | {'cleanup_pending': bool(metadata.get('cleanup_keys'))}
    # DynamoDB deserializes numbers as Decimal; never leak storage types to JSON.
    safe['size_bytes'] = int(metadata['size_bytes'])
    return safe


class MediaService:
    def __init__(self, customers, storage):
        self.customers, self.repository, self.storage = customers, customers.repository, storage

    def _prefix(self, business, customer, kind):
        return f'businesses/{business}/customers/{customer}/{KINDS[kind]}/'

    def _checked_key(self, business, customer, kind, key):
        if not isinstance(key, str) or not re.fullmatch(re.escape(self._prefix(business, customer, kind)) + r'[0-9a-f]{32}\.(jpg|png|webp)', key):
            raise MediaUnavailable()
        return key

    def _validate_metadata(self, business, customer, kind, metadata):
        if (not isinstance(metadata, dict) or metadata.get('content_type') not in FORMATS or
                not isinstance(metadata.get('revision'), str) or
                not re.fullmatch(r'[0-9a-f]{32}', metadata['revision']) or
                not isinstance(metadata.get('cleanup_keys', []), list)):
            raise MediaUnavailable()
        self._checked_key(business, customer, kind, metadata.get('key'))
        for key in metadata.get('cleanup_keys', []): self._checked_key(business, customer, kind, key)

    def metadata(self, business, customer, kind):
        self.customers.get(business, customer)
        metadata = self.repository.get_media(business, customer, KINDS[kind])
        if metadata is None: raise MediaNotFound()
        self._validate_metadata(business, customer, kind, metadata)
        return metadata

    def image(self, business, customer, kind, revision=None):
        metadata = self.metadata(business, customer, kind)
        if revision is not None and revision != metadata['revision']: raise ConcurrentModification()
        return self.storage.get(metadata['key']), metadata['content_type']

    def upload(self, user, customer_id, kind, data, content_type, document_type=None):
        customer = self.customers.get(user.business_id, customer_id)
        if kind == 'id-document' and document_type not in DOCUMENT_TYPES: raise InvalidImage()
        encoded, suffix = validated_image(data, content_type)
        old = self.repository.get_media(user.business_id, customer_id, KINDS[kind])
        key = self._prefix(user.business_id, customer_id, kind) + uuid4().hex + '.' + suffix
        pending = []
        if old:
            self._validate_metadata(user.business_id, customer_id, kind, old)
            pending = list(dict.fromkeys([old['key'], *old.get('cleanup_keys', [])]))
            for previous in pending: self._checked_key(user.business_id, customer_id, kind, previous)
        now = datetime.now(timezone.utc).isoformat()
        metadata = {'key': key, 'revision': uuid4().hex, 'content_type': content_type,
                    'size_bytes': len(encoded), 'uploaded_at': now, 'uploaded_by': user.subject,
                    'cleanup_keys': pending}
        if kind == 'id-document':
            metadata.update(document_type=document_type, verification_status='Pending', verified_at=None, verified_by=None)
        elif kind == 'consent-evidence':
            metadata.update(evidence_type='signed_marketing_consent', related_consent_timestamp=customer.consent_timestamp.isoformat() if customer.consent_timestamp else None)
        self.storage.put(key, encoded, content_type)
        try:
            self.repository.save_media(user.business_id, customer_id, KINDS[kind], metadata, expected_revision=old['revision'] if old else None)
        except ConcurrentModification:
            self._discard(key)
            raise
        except StorageUnavailable:
            # A timed-out write might have committed. Reconcile before deleting
            # the new object so a successful metadata write never loses its image.
            try: current = self.repository.get_media(user.business_id, customer_id, KINDS[kind])
            except StorageUnavailable:
                logger.warning('Media upload outcome uncertain; private object reconciliation required.')
                raise MediaUnavailable() from None
            if not current or current.get('revision') != metadata['revision']:
                self._discard(key)
                raise MediaUnavailable() from None
        failed = []
        for previous in pending:
            try: self.storage.delete(previous)
            except MediaUnavailable: failed.append(previous)
        if failed != pending:
            cleaned = {**metadata, 'cleanup_keys': failed}
            try:
                self.repository.save_media(user.business_id, customer_id, KINDS[kind], cleaned, expected_revision=metadata['revision'])
                metadata = cleaned
            except (ConcurrentModification, StorageUnavailable):
                # A later replacement inherited the pending keys; retries are safe.
                pass
        if failed: logger.warning('Media replacement saved; private old-object cleanup pending.')
        return public_metadata(metadata)

    def _discard(self, key):
        try: self.storage.delete(key)
        except MediaUnavailable: logger.warning('Uncommitted private media cleanup failed; reconciliation required.')

    def verify(self, user, customer_id, revision, status):
        old = self.metadata(user.business_id, customer_id, 'id-document')
        if old['revision'] != revision: raise ConcurrentModification()
        updated = {**old, 'revision': uuid4().hex, 'verification_status': status,
                   'verified_by': user.subject, 'verified_at': datetime.now(timezone.utc).isoformat()}
        self.repository.save_media(user.business_id, customer_id, 'identity', updated, expected_revision=revision)
        return public_metadata(updated)
