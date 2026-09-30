from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.repository import DuplicatePhone, InMemoryCustomerRepository
from app.routes import router
from app.service import CustomerNotFound, CustomerService


def create_app(repository=None):
    app = FastAPI(title='Loyalty Platform API', version='0.2.0')
    app.state.customer_service = CustomerService(repository if repository is not None else InMemoryCustomerRepository())
    app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'], allow_methods=['GET', 'POST', 'PUT'], allow_headers=['Content-Type'])
    app.include_router(router)

    @app.exception_handler(DuplicatePhone)
    async def duplicate_phone(request: Request, exc: DuplicatePhone):
        return JSONResponse(status_code=409, content={'detail': 'A customer with this phone number already exists in this business.'})

    @app.exception_handler(CustomerNotFound)
    async def not_found(request: Request, exc: CustomerNotFound):
        return JSONResponse(status_code=404, content={'detail': 'Customer not found.'})

    @app.get('/')
    def root():
        return {'message': 'Loyalty Platform API is running', 'version': '0.2.0'}

    @app.get('/health')
    def health():
        return {'status': 'healthy'}

    return app


app = create_app()
