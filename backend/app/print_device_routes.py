"""Isolated DEVELOPMENT device transport. Never usable with DynamoDB/production.
Production needs a separately provisioned revocable device issuer and enrollment.
No human Cognito token is accepted here; device has only queue lifecycle access.
"""
import os
import re
import secrets
from dataclasses import dataclass
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from .repository import InMemoryCustomerRepository
from .print_routes import Empty, ClaimToken, Service

router = APIRouter(prefix='/development/print-agent', tags=['Development print agent'])

@dataclass(frozen=True)
class Device:
    subject: str
    business_id: str


def device(request: Request):
    repository = request.app.state.print_service.repository
    # Explicit opt-in, loopback caller and memory storage: fails closed on real data.
    if (os.getenv('APP_ENV') != 'development' or os.getenv('PRINT_AGENT_DEV_ENABLED') != 'true'
            or type(repository) is not InMemoryCustomerRepository
            or not request.client or request.client.host not in {'127.0.0.1', '::1', 'testclient'}):
        raise HTTPException(404, 'Not found.')
    secret = os.getenv('PRINT_AGENT_DEV_SECRET', '')
    business = os.getenv('PRINT_AGENT_DEV_BUSINESS', '')
    identity = os.getenv('PRINT_AGENT_DEV_ID', '')
    if (len(secret) < 32 or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', business)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', identity)):
        raise HTTPException(503, 'Development device configuration unavailable.')
    supplied = request.headers.get('Authorization', '')
    if not secrets.compare_digest(supplied.encode(), ('Bearer ' + secret).encode()):
        raise HTTPException(401, 'Device authentication required.')
    return Device('device:' + identity, business)

DeviceUser = Annotated[Device, Depends(device)]

@router.get('/jobs')
def jobs(user: DeviceUser, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return [job for job in service.listing(user) if job['status'] in {'PENDING', 'RETRYABLE'}]

@router.post('/jobs/{job_id}/claim')
def claim(job_id: str, data: Empty, user: DeviceUser, service: Service, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return service.action(user, job_id, 'claim')

@router.post('/jobs/{job_id}/{action}')
def action(job_id: str, action: str, data: ClaimToken, user: DeviceUser, service: Service, response: Response):
    if action not in {'start', 'fail', 'renew', 'submitted'}: raise HTTPException(404, 'Not found.')
    response.headers['Cache-Control'] = 'no-store'
    return service.action(user, job_id, action, data.claim_token)
