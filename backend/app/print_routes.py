from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from .auth import UserContext, require_management
from .routes import customer_user
from .print_service import PrintService

router = APIRouter(tags=['Print queue'])
User = Annotated[UserContext, Depends(customer_user)]
Management = Annotated[UserContext, Depends(require_management)]


def service(request: Request): return request.app.state.print_service
Service = Annotated[PrintService, Depends(service)]


class Empty(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ClaimToken(Empty):
    claim_token: str = Field(min_length=43, max_length=43, pattern=r'^[A-Za-z0-9_-]+$')


class ReprintInput(Empty):
    request_id: UUID
    reason: str = Field(min_length=5, max_length=300)
    confirmed: bool


@router.get('/print-jobs')
def queue(user: User, management: Management, service: Service, response: Response, review: bool = False):
    response.headers['Cache-Control'] = 'no-store'
    return service.listing(user, review=review)


@router.get('/customers/{customer_id}/print-jobs')
def customer_jobs(customer_id: str, user: User, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.listing(user, customer_id=customer_id)


@router.get('/customers/{customer_id}/visits/{visit_id}/print-jobs')
def visit_jobs(customer_id: str, visit_id: str, user: User, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.listing(user, customer_id=customer_id, visit_id=visit_id)


@router.get('/print-jobs/{job_id}')
def detail(job_id: str, user: User, management: Management, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.detail(user, job_id)


@router.post('/print-jobs/{job_id}/claim')
def claim(job_id: str, data: Empty, user: User, management: Management, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.action(user, job_id, 'claim')


@router.post('/print-jobs/{job_id}/start')
def start(job_id: str, data: ClaimToken, user: User, management: Management, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.action(user, job_id, 'start', data.claim_token)


@router.post('/print-jobs/{job_id}/complete')
def complete(job_id: str, data: ClaimToken, user: User, management: Management, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.action(user, job_id, 'complete', data.claim_token)


@router.post('/print-jobs/{job_id}/fail')
def fail(job_id: str, data: ClaimToken, user: User, management: Management, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.action(user, job_id, 'fail', data.claim_token)


@router.post('/print-jobs/{job_id}/review')
def review(job_id: str, data: Empty, user: User, management: Management, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.action(user, job_id, 'review')


@router.post('/print-jobs/{job_id}/reprint', status_code=201)
def reprint(job_id: str, data: ReprintInput, user: User, management: Management, service: Service, response: Response):
    from .print_models import PrintJobConflict
    if not data.confirmed: raise PrintJobConflict('Confirm the explicit reprint request before continuing.')
    response.headers['Cache-Control'] = 'no-store'
    return service.reprint(user, job_id, data.request_id, data.reason)
