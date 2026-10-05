"""Backend-only configuration. No credentials are stored by the application."""
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    customer_repository: str
    aws_region: str
    dynamodb_customers_table: str | None
    aws_profile: str | None

    @classmethod
    def from_environment(cls):
        # Explicit process environment wins over the optional backend/.env file.
        load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
        mode = os.getenv('CUSTOMER_REPOSITORY', 'memory').strip().lower()
        if mode not in {'memory', 'dynamodb'}:
            raise ValueError('CUSTOMER_REPOSITORY must be memory or dynamodb.')
        table = os.getenv('DYNAMODB_CUSTOMERS_TABLE', '').strip() or None
        if mode == 'dynamodb' and not table:
            raise ValueError('DYNAMODB_CUSTOMERS_TABLE is required for DynamoDB storage.')
        return cls(mode, os.getenv('AWS_REGION', 'eu-west-1').strip(), table,
                   os.getenv('AWS_PROFILE', '').strip() or None)


def build_repository(settings: Settings):
    if settings.customer_repository == 'memory':
        from .repository import InMemoryCustomerRepository
        return InMemoryCustomerRepository()

    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError
    from .dynamodb_repository import DynamoDBCustomerRepository
    from .repository import StorageUnavailable

    try:
        session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
        client = session.client('dynamodb', config=Config(
            retries={'mode': 'standard', 'total_max_attempts': 3},
            connect_timeout=3, read_timeout=10,
        ))
    except BotoCoreError as exc:
        raise StorageUnavailable('Customer storage could not be initialized. Check backend AWS configuration.') from exc
    return DynamoDBCustomerRepository(client, settings.dynamodb_customers_table)
