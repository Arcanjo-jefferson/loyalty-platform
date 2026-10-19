"""No network implementation exists. A future Twilio adapter requires separate approval."""
from typing import Protocol
from dataclasses import dataclass


class SafeRetry(Exception):
    """Provider guarantees no submission occurred; bounded retry is safe."""


@dataclass(frozen=True)
class Delivery:
    status: str
    provider_id: str


class SMSProvider(Protocol):
    def send(self, *, sender: str, destination: str, body: str, message_id: str) -> Delivery: ...


class SimulatedSMSProvider:
    def send(self, *, sender, destination, body, message_id):
        # Deliberately no SDK, sockets, credentials, real delivery claim or body logging.
        return Delivery('SIMULATED', 'simulation:' + message_id)
