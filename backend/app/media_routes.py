"""Authenticated media endpoints: no frontend-chosen keys or download URLs."""
import json
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from .auth import Role, UserContext, authenticated_user
from .media_service import KINDS, public_metadata
from .media_storage import MAX_IMAGE_BYTES

router = APIRouter(prefix='/customers', tags=['Customer media'])
Kind = Literal['profile-photo', 'id-document', 'consent-evidence']
User = Annotated[UserContext, Depends(authenticated_user)]


def authorize(request, user, customer_id, kind):
    if kind not in KINDS: raise HTTPException(404, 'Media category not found.')
    if kind != 'profile-photo' and user.role not in {Role.OWNER, Role.MANAGER}:
        raise HTTPException(403, 'Only Owner or Manager may access this document.')
    # Never use the query to select a tenant or S3 key.
    if 'business_id' in request.query_params and request.query_params['business_id'] != user.business_id:
        raise HTTPException(403, 'You do not have access to this business.')
    request.app.state.customer_service.get(user.business_id, customer_id)
    return request.app.state.media_service


@router.get('/{customer_id}/{kind}')
def metadata(customer_id: str, kind: Kind, request: Request, user: User):
    service = authorize(request, user, customer_id, kind)
    return Response(json.dumps(public_metadata(service.metadata(user.business_id, customer_id, kind))),
                    media_type='application/json', headers={'Cache-Control': 'no-store'})


@router.get('/{customer_id}/{kind}/image')
def image(customer_id: str, kind: Kind, request: Request, user: User, revision: str | None = None):
    service = authorize(request, user, customer_id, kind)
    data, content_type = service.image(user.business_id, customer_id, kind, revision)
    return Response(data, media_type=content_type, headers={'Cache-Control': 'no-store, private',
                    'X-Content-Type-Options': 'nosniff', 'Content-Disposition': 'inline', 'Referrer-Policy': 'no-referrer'})


@router.post('/{customer_id}/{kind}', status_code=201)
async def upload(customer_id: str, kind: Kind, request: Request, user: User):
    service = await run_in_threadpool(authorize, request, user, customer_id, kind)
    allowed = {'business_id', 'document_type'}
    if any(key not in allowed for key in request.query_params):
        raise HTTPException(422, 'Unsupported upload parameter.')
    content_type = request.headers.get('content-type', '').split(';')[0].strip().lower()
    from .media_service import FORMATS, DOCUMENT_TYPES
    if content_type not in FORMATS: raise HTTPException(415, 'Use a JPEG, PNG or WebP image.')
    document_type = request.query_params.get('document_type')
    if kind == 'id-document' and document_type not in DOCUMENT_TYPES:
        raise HTTPException(422, 'Select a supported ID document type.')
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_IMAGE_BYTES: raise HTTPException(413, 'Image must be 5 MiB or smaller.')
        data.extend(chunk)
    result = await run_in_threadpool(service.upload, user, customer_id, kind, bytes(data), content_type, document_type)
    return Response(json.dumps(result), status_code=201, media_type='application/json', headers={'Cache-Control': 'no-store'})


class VerificationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: str = Field(pattern=r'^[0-9a-f]{32}$')
    status: Literal['Verified', 'Rejected']


@router.patch('/{customer_id}/id-document/verification')
def verify(customer_id: str, body: VerificationInput, request: Request, user: User):
    service = authorize(request, user, customer_id, 'id-document')
    result = service.verify(user, customer_id, body.revision, body.status)
    return Response(json.dumps(result), media_type='application/json', headers={'Cache-Control': 'no-store'})
