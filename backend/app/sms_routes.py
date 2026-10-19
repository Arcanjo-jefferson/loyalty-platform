"""All SMS operations require human Owner/Manager; verified tenant only."""
from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Response, HTTPException, Query
from .auth import UserContext, require_management
from .routes import customer_user
from .sms_models import Compose, Confirm
from .print_routes import Empty

router = APIRouter(prefix='/sms', tags=['SMS simulation'])
Management = Annotated[UserContext, Depends(require_management)]
Scoped = Annotated[UserContext, Depends(customer_user)]


def service(request: Request): return request.app.state.sms_service
Service = Annotated[object, Depends(service)]


@router.get('/customers')
def customers(user: Management, scoped: Scoped, service: Service, response: Response,
              q: Annotated[str, Query(max_length=100)] = ''):
    response.headers['Cache-Control'] = 'no-store'
    return service.search_customers(user.business_id, q)


@router.get('/settings')
def settings(user: Management, scoped: Scoped, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.summary(user.business_id)


@router.post('/preview')
def preview(data: Compose, user: Management, scoped: Scoped, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.preview(user, data)


@router.post('/campaigns/{identity}/confirm')
def confirm(identity: UUID, data: Confirm, user: Management, scoped: Scoped, service: Service, response: Response, request: Request):
    response.headers['Cache-Control'] = 'no-store'
    result = service.confirm(user, str(identity), data.confirmed)
    request.app.state.sms_worker.notify(user.business_id)
    return result


@router.get('/campaigns/{identity}')
def campaign(identity: UUID, user: Management, scoped: Scoped, service: Service, response: Response, request: Request):
    response.headers['Cache-Control'] = 'no-store'
    result = service.view(service.get(user.business_id, str(identity)))
    request.app.state.sms_worker.notify(user.business_id)
    return result


@router.get('/history')
def history(user: Management, scoped: Scoped, service: Service, response: Response, request: Request):
    response.headers['Cache-Control'] = 'no-store'
    request.app.state.sms_worker.notify(user.business_id)
    return service.history(user.business_id)


@router.post('/simulate')
def simulate(data: Empty, user: Management, scoped: Scoped, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.process(user.business_id)


@router.post('/customers/{customer_id}/suppress')
def suppress(customer_id: UUID, data: Confirm, user: Management, scoped: Scoped, service: Service, response: Response):
    if not data.confirmed: raise HTTPException(422, 'Confirm the customer SMS opt-out.')
    response.headers['Cache-Control'] = 'no-store'
    return service.suppress(user, customer_id)
