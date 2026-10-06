from typing import Annotated
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from .routes import customer_user
from .auth import UserContext
from .loyalty_service import LoyaltyService

router = APIRouter(tags=['Loyalty visits'])
User = Annotated[UserContext, Depends(customer_user)]


def service(request: Request): return request.app.state.loyalty_service
Service = Annotated[LoyaltyService, Depends(service)]


class QRLookupInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    qr_token: str = Field(pattern=r'^[A-Za-z0-9_-]{16,128}$')


class VisitInput(BaseModel):
    model_config = ConfigDict(extra='forbid')


@router.post('/loyalty/lookup')
def lookup(data: QRLookupInput, user: User, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.lookup(user.business_id, data.qr_token)


@router.post('/customers/{customer_id}/visits', status_code=201)
def confirm(customer_id: str, data: VisitInput, user: User, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.confirm(user, customer_id)


@router.get('/customers/{customer_id}/visits')
def history(customer_id: str, user: User, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.history(user.business_id, customer_id)
