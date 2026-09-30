from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request
from .models import Customer, CustomerInput
from .service import CustomerService

router = APIRouter(prefix='/customers', tags=['customers'])
Business = Annotated[str, Query(min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')]


def service(request: Request) -> CustomerService:
    return request.app.state.customer_service

Service = Annotated[CustomerService, Depends(service)]


@router.post('', response_model=Customer, status_code=201)
def create_customer(data: CustomerInput, service: Service, business_id: Business = 'trumps'):
    return service.create(business_id, data)


@router.get('', response_model=list[Customer])
def list_customers(service: Service, business_id: Business = 'trumps'):
    return service.list(business_id)


@router.get('/{customer_id}', response_model=Customer)
def get_customer(customer_id: str, service: Service, business_id: Business = 'trumps'):
    return service.get(business_id, customer_id)


@router.put('/{customer_id}', response_model=Customer)
def update_customer(customer_id: str, data: CustomerInput, service: Service, business_id: Business = 'trumps'):
    return service.update(business_id, customer_id, data)
