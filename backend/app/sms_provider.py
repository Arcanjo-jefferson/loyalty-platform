"""Provider factory and hard delivery barrier. No SDK, HTTP or socket transport."""
import os
from .sms_contracts import (Delivery, SendRequest, SMSProvider, SafeRetry,
                            ProviderUnavailable, PermanentProviderError, UncertainProviderError)


class SimulatedSMSProvider:
    def send(self, request: SendRequest) -> Delivery:
        return Delivery(status='SIMULATED', provider_id='simulation:' + request.message_id)


class DisabledProvider:
    def send(self, request: SendRequest) -> Delivery:
        raise ProviderUnavailable('Real SMS delivery is unavailable in this release.')

    def verify_incoming(self, *, body, headers, url):
        raise ProviderUnavailable('SMS webhooks are not implemented.')

    def verify_delivery(self, *, body, headers, url):
        raise ProviderUnavailable('SMS webhooks are not implemented.')

    def verify_stop(self, *, body, headers, url):
        raise ProviderUnavailable('SMS webhooks are not implemented.')


class TwilioSMSProvider(DisabledProvider):
    """Disabled placeholder; no Twilio credentials, SDK or transport."""


class ClickSendSMSProvider(DisabledProvider):
    """Disabled placeholder; no ClickSend credentials, SDK or transport."""


def build_provider(name: str) -> SMSProvider:
    providers = {'simulation': SimulatedSMSProvider, 'twilio': TwilioSMSProvider,
                 'clicksend': ClickSendSMSProvider}
    if name not in providers: raise ValueError('Unknown SMS provider.')
    return providers[name]()


def require_simulation(name: str):
    # No environment setting can enable real delivery in this milestone.
    flag = os.getenv('SMS_REAL_DELIVERY_ENABLED', 'false').strip().lower()
    if flag != 'false' or name != 'simulation':
        raise ProviderUnavailable('SMS provider is disabled. Only simulation is available.')


def provider_identity(name: str) -> str:
    build_provider(name)  # Validate against the allowlist, never dynamic imports.
    return name + ':v1'


def require_worker_provider(provider):
    """Keep injected arbitrary transports out of the automatic worker.
    The normal path resolves exclusively through this module's allowlisted factory.
    """
    if provider is not None and type(provider) is not SimulatedSMSProvider:
        raise ProviderUnavailable('Automatic SMS worker only supports simulation.')
