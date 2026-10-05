from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import Settings, build_repository
from app.repository import ConcurrentModification, DuplicatePhone, StorageUnavailable
from app.routes import router
from app.service import CustomerNotFound, CustomerService


def create_app(repository=None):
    app = FastAPI(title='Loyalty Platform API', version='0.3.0')
    app.state.customer_service = CustomerService(repository if repository is not None else build_repository(Settings.from_environment()))
    app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'], allow_methods=['GET', 'POST', 'PUT'], allow_headers=['Content-Type'])
    app.include_router(router)

    @app.exception_handler(DuplicatePhone)
    async def duplicate_phone(request: Request, exc: DuplicatePhone):
        return JSONResponse(status_code=409, content={'detail': 'A customer with this phone number already exists in this business.'})

    @app.exception_handler(CustomerNotFound)
    async def not_found(request: Request, exc: CustomerNotFound):
        return JSONResponse(status_code=404, content={'detail': 'Customer not found.'})

    @app.exception_handler(StorageUnavailable)
    async def storage_unavailable(request: Request, exc: StorageUnavailable):
        return JSONResponse(status_code=503, content={'detail': 'Customer storage is temporarily unavailable. Please try again or check the backend AWS configuration.'})

    @app.exception_handler(ConcurrentModification)
    async def concurrent_modification(request: Request, exc: ConcurrentModification):
        return JSONResponse(status_code=409, content={'detail': 'This customer changed during the request. Reload the customer and try again.'})

    @app.get('/')
    def root():
        return {'message': 'Loyalty Platform API is running', 'version': '0.3.0'}

    @app.get('/health')
    def health():
        return {'status': 'healthy'}

    return app


app = create_app()
