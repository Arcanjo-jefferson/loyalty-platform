from io import BytesIO
import qrcode
from qrcode.image.pil import PilImage
from .service import CustomerNotFound


def qr_png(token):
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    code.add_data(token, optimize=0)
    code.make(fit=True)
    output = BytesIO()
    code.make_image(image_factory=PilImage, fill_color='black', back_color='white').save(output, format='PNG')
    return output.getvalue()


class QRService:
    def __init__(self, customers): self.customers, self.repository = customers, customers.repository
    def link(self, business_id, customer_id):
        self.customers.get(business_id, customer_id)
        customer, reference = self.repository.manage_qr(business_id, customer_id)
        return {'qr_token': customer.qr_token, 'public_reference': reference}
    def regenerate(self, business_id, customer_id, expected_token):
        self.customers.get(business_id, customer_id)
        customer, reference = self.repository.manage_qr(business_id, customer_id, expected_token=expected_token)
        return {'qr_token': customer.qr_token, 'public_reference': reference}
    def image(self, business_id, customer_id):
        return qr_png(self.customers.get(business_id, customer_id).qr_token)
    def public_image(self, reference): return qr_png(self.repository.public_qr_token(reference))
