from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from .auth import UserContext, authenticated_user, require_customer_access, authorize_customer_status
from .models import Customer, CustomerInput
from .service import CustomerService

router = APIRouter(prefix='/customers', tags=['customers'])


def service(request: Request) -> CustomerService:
    return request.app.state.customer_service


def customer_user(user: Annotated[UserContext, Depends(require_customer_access)], business_id: Annotated[str | None, Query()] = None):
    # Compatibility only: a matching query is accepted; it never selects the tenant.
    if business_id is not None and business_id != user.business_id:
        raise HTTPException(403, 'You do not have access to this business.')
    return user


Service = Annotated[CustomerService, Depends(service)]
User = Annotated[UserContext, Depends(customer_user)]


@router.post('', response_model=Customer, status_code=201)
def create_customer(data: CustomerInput, service: Service, user: User):
    authorize_customer_status(user, 'active', data.status)
    return service.create(user.business_id, data)


@router.get('', response_model=list[Customer])
def list_customers(service: Service, user: User):
    return service.list(user.business_id)


@router.get('/{customer_id}', response_model=Customer)
def get_customer(customer_id: str, service: Service, user: User):
    return service.get(user.business_id, customer_id)


@router.put('/{customer_id}', response_model=Customer)
def update_customer(customer_id: str, data: CustomerInput, service: Service, user: User):
    current = service.get(user.business_id, customer_id)
    authorize_customer_status(user, current.status, data.status)
    return service.update(user.business_id, customer_id, data, existing=current)


identity_router = APIRouter(tags=['authentication'])


@identity_router.get('/auth/me')
def current_identity(user: Annotated[UserContext, Depends(authenticated_user)]):
    return {'subject': user.subject, 'email': user.email, 'business_id': user.business_id, 'role': user.role}
