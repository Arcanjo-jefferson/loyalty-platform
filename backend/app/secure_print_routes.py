"""Separate machine queue API and Owner-only pending device management."""
from typing import Annotated
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from pydantic import Field
from .auth import require_owner, UserContext
from .print_agent_auth import agent, AgentPrincipal
from .print_routes import Service, Empty, ClaimToken

router=APIRouter()
Machine=Annotated[AgentPrincipal,Depends(agent)]
Owner=Annotated[UserContext,Depends(require_owner)]

class Registration(Empty):
    label: str = Field(min_length=1,max_length=80,pattern=r'^[^\x00-\x1f\x7f]+$')

@router.get('/print-agent/jobs')
def jobs(user:Machine,service:Service,response:Response):
    response.headers['Cache-Control']='no-store'
    return [job for job in service.listing(user) if job['status'] in {'PENDING','RETRYABLE'}]

@router.post('/print-agent/jobs/{job_id}/claim')
def claim(job_id:str,data:Empty,user:Machine,service:Service,response:Response):
    response.headers['Cache-Control']='no-store'
    return service.action(user,job_id,'claim')

@router.post('/print-agent/jobs/{job_id}/{action}')
def action(job_id:str,action:str,data:ClaimToken,user:Machine,service:Service,response:Response):
    if action not in {'start','renew','fail','submitted'}: raise HTTPException(404,'Not found.')
    response.headers['Cache-Control']='no-store'
    return service.action(user,job_id,action,data.claim_token)

@router.get('/print-devices')
def devices(user:Owner,request:Request,response:Response):
    response.headers['Cache-Control']='no-store'
    return request.app.state.device_registry.listing(user.business_id)

@router.post('/print-devices',status_code=201)
def register(data:Registration,user:Owner,request:Request,response:Response):
    response.headers['Cache-Control']='no-store'
    return request.app.state.device_registry.register(user.business_id,user.subject,data.label)

@router.post('/print-devices/{device_id}/{action}')
def manage(device_id:str,action:str,data:Empty,user:Owner,request:Request,response:Response):
    if action not in {'disable','rotate'}: raise HTTPException(404,'Not found.')
    response.headers['Cache-Control']='no-store'
    return request.app.state.device_registry.update(user.business_id,device_id,user.subject,action)
