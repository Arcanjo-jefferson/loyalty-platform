from typing import Annotated
from fastapi import APIRouter, Depends, Request, Response
from .auth import UserContext
from .routes import customer_user
from .raffle import RaffleService

router = APIRouter(tags=['Daily Raffle'])
User = Annotated[UserContext, Depends(customer_user)]


def service(request: Request):
    return request.app.state.raffle_service


@router.get('/customers/{customer_id}/raffle-entries')
def history(customer_id: str, user: User, response: Response,
            service: Annotated[RaffleService, Depends(service)]):
    response.headers['Cache-Control'] = 'no-store'
    return service.history(user.business_id, customer_id)
