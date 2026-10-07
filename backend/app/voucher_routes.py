from typing import Annotated
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from .auth import UserContext
from .routes import customer_user
from .voucher_service import VoucherService

router = APIRouter(tags=['Vouchers'])
User = Annotated[UserContext, Depends(customer_user)]


def service(request: Request): return request.app.state.voucher_service
Service = Annotated[VoucherService, Depends(service)]


class CodeInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    voucher_code: str = Field(min_length=1, max_length=100)


class RedemptionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')


@router.get('/customers/{customer_id}/vouchers')
def listing(customer_id: str, user: User, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.list(user.business_id, customer_id)


@router.post('/vouchers/lookup')
def lookup(data: CodeInput, user: User, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.lookup(user.business_id, data.voucher_code)


@router.post('/customers/{customer_id}/vouchers/{voucher_id}/redeem')
def redeem(customer_id: str, voucher_id: str, data: RedemptionInput, user: User, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.redeem(user, customer_id, voucher_id)
