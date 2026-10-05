"""Test-only ASGI application. Never used by the production main:app entrypoint."""
from app.auth import Role, UserContext, InvalidAuthentication
from app.repository import InMemoryCustomerRepository
from main import create_app


class FixtureVerifier:
    def verify(self, token):
        if not token.startswith('fixture:'):
            raise InvalidAuthentication()
        return UserContext('fixture-user', None, token.removeprefix('fixture:'), ('Owner',), Role.OWNER)


app = create_app(InMemoryCustomerRepository(), FixtureVerifier())
