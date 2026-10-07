from typing import Annotated
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .auth import UserContext, require_management
from .routes import customer_user
from .qr_service import QRService
import re

router = APIRouter(tags=['Customer QR'])
User = Annotated[UserContext, Depends(customer_user)]
Management = Annotated[UserContext, Depends(require_management)]


def service(request: Request): return request.app.state.qr_service
Service = Annotated[QRService, Depends(service)]


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra='forbid')


class RegenerateInput(EmptyInput):
    expected_qr_token: str = Field(pattern=r'^[A-Za-z0-9_-]{16,128}$')
    confirmed: bool


def image_response(image):
    return Response(image, media_type='image/png', headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff'})


@router.post('/customers/{customer_id}/qr/link')
def link(customer_id: str, data: EmptyInput, user: User, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.link(user.business_id, customer_id)


@router.get('/customers/{customer_id}/qr/image')
def image(customer_id: str, user: User, service: Service): return image_response(service.image(user.business_id, customer_id))


@router.post('/customers/{customer_id}/qr/regenerate')
def regenerate(customer_id: str, data: RegenerateInput, user: User, management: Management, service: Service, response: Response):
    if not data.confirmed: raise HTTPException(422, 'Confirm QR regeneration before continuing.')
    response.headers['Cache-Control'] = 'no-store'
    return service.regenerate(user.business_id, customer_id, data.expected_qr_token)


@router.post('/customers/{customer_id}/qr/send')
def send(customer_id: str, data: EmptyInput, user: User, service: Service):
    service.customers.get(user.business_id, customer_id)
    raise HTTPException(501, 'SMS sending is not configured yet. Use Copy QR Link.')


@router.get('/public/qr/{reference}/image')
def public_image(reference: str, service: Service):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', reference): raise HTTPException(404, 'QR link is unavailable.')
    return image_response(service.public_image(reference))
