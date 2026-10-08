from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.print_routes import router as print_router
from app.print_device_routes import router as device_router
from app.print_service import PrintService
from app.print_models import PrintJobNotFound, PrintJobConflict
from app.raffle_routes import router as raffle_router
from app.raffle import RaffleService
from app.qr_routes import router as qr_router
from app.qr_service import QRService
from app.qr_repository import QRNotFound
from app.voucher_routes import router as voucher_router
from app.voucher_service import VoucherService
from app.voucher_repository import VoucherNotFound, VoucherNotRedeemable
from app.loyalty_routes import router as loyalty_router
from app.loyalty_service import LoyaltyService
from app.repository import DuplicateQR, DuplicateVisit, InactiveCustomer
from app.media_routes import router as media_router
from app.media_service import MediaService, InvalidImage, ImageTooLarge, MediaNotFound
from app.media_storage import build_media_storage, MediaUnavailable
from app.config import Settings, build_repository
from app.repository import ConcurrentModification, DuplicatePhone, StorageUnavailable
from app.routes import identity_router, router
from app.auth import CognitoVerifier
from app.service import CustomerNotFound, CustomerService


def create_app(repository=None, token_verifier=None, media_storage=None):
    app = FastAPI(title='Loyalty Platform API', version='0.7.0')
    app.state.customer_service = CustomerService(repository if repository is not None else build_repository(Settings.from_environment()))
    app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'], allow_methods=['GET', 'POST', 'PUT', 'PATCH'], allow_headers=['Content-Type', 'Authorization'])
    app.state.token_verifier = token_verifier if token_verifier is not None else CognitoVerifier.from_environment()
    app.include_router(router)
    app.include_router(identity_router)
    app.state.media_service = MediaService(app.state.customer_service, media_storage if media_storage is not None else build_media_storage())
    app.state.loyalty_service = LoyaltyService(app.state.customer_service)
    # Specific visit routes must precede the media category catch-all.
    app.state.voucher_service = VoucherService(app.state.customer_service)
    app.state.qr_service = QRService(app.state.customer_service)
    app.state.raffle_service = RaffleService(app.state.customer_service)
    app.state.print_service = PrintService(app.state.customer_service)
    app.include_router(print_router)
    app.include_router(device_router)
    app.include_router(raffle_router)
    app.include_router(qr_router)
    app.include_router(voucher_router)
    app.include_router(loyalty_router)
    app.include_router(media_router)

    @app.exception_handler(PrintJobNotFound)
    async def print_not_found(request, exc):
        return JSONResponse(status_code=404, content={'detail': 'Print job not found.'}, headers={'Cache-Control': 'no-store'})

    @app.exception_handler(PrintJobConflict)
    async def print_conflict(request, exc):
        return JSONResponse(status_code=409, content={'detail': str(exc) or 'Print job changed. Refresh before trying again.'}, headers={'Cache-Control': 'no-store'})

    @app.exception_handler(QRNotFound)
    async def qr_not_found(request, exc):
        return JSONResponse(status_code=404, content={'detail': 'QR link is unavailable.'}, headers={'Cache-Control': 'no-store'})

    @app.exception_handler(VoucherNotFound)
    async def voucher_not_found(request, exc):
        return JSONResponse(status_code=404, content={'detail': 'Voucher not found.'})

    @app.exception_handler(VoucherNotRedeemable)
    async def voucher_not_redeemable(request, exc):
        return JSONResponse(status_code=409, content={'detail': 'This voucher has expired or has already been redeemed.'})

    @app.exception_handler(DuplicateQR)
    async def duplicate_qr(request, exc):
        return JSONResponse(status_code=409, content={'detail': 'This QR identifier is already assigned. Contact your administrator.'})

    @app.exception_handler(DuplicateVisit)
    async def duplicate_visit(request, exc):
        return JSONResponse(status_code=409, content={'detail': 'A loyalty visit has already been recorded for this customer today.'})

    @app.exception_handler(InactiveCustomer)
    async def inactive_customer(request, exc):
        return JSONResponse(status_code=409, content={'detail': 'Inactive customers cannot register visits.'})

    @app.exception_handler(MediaUnavailable)
    async def media_unavailable(request, exc):
        return JSONResponse(status_code=503, content={'detail': 'Customer media is temporarily unavailable. Check backend storage configuration or try again.'})

    @app.exception_handler(InvalidImage)
    async def invalid_image(request, exc):
        return JSONResponse(status_code=422, content={'detail': 'Use a valid, non-animated JPEG, PNG or WebP image, up to 20 million pixels.'})

    @app.exception_handler(ImageTooLarge)
    async def oversized_image(request, exc):
        return JSONResponse(status_code=413, content={'detail': 'Image must be 5 MiB or smaller.'})

    @app.exception_handler(MediaNotFound)
    async def media_not_found(request, exc):
        return JSONResponse(status_code=404, content={'detail': 'No image has been uploaded.'})

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
        return {'message': 'Loyalty Platform API is running', 'version': '0.7.0'}

    @app.get('/health')
    def health():
        return {'status': 'healthy'}

    return app


app = create_app()
