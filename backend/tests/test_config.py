import os
import unittest
from unittest.mock import patch
from app.config import Settings, build_repository
from app.repository import InMemoryCustomerRepository, StorageUnavailable
from botocore.exceptions import ProfileNotFound


class RepositoryConfigurationTests(unittest.TestCase):
    def settings(self, environment):
        with patch.dict(os.environ, environment, clear=True), patch('app.config.load_dotenv'):
            return Settings.from_environment()

    def test_default_and_explicit_memory_do_not_access_aws(self):
        with patch('boto3.Session') as session:
            self.assertIsInstance(build_repository(self.settings({})), InMemoryCustomerRepository)
            self.assertIsInstance(build_repository(self.settings({'CUSTOMER_REPOSITORY': 'memory', 'AWS_PROFILE': 'nonexistent'})), InMemoryCustomerRepository)
            session.assert_not_called()

    def test_dynamodb_configuration_and_local_profile(self):
        settings = self.settings({'CUSTOMER_REPOSITORY': 'dynamodb', 'DYNAMODB_CUSTOMERS_TABLE': 'test-table', 'AWS_PROFILE': 'test-profile'})
        with patch('boto3.Session') as session:
            repository = build_repository(settings)
            session.assert_called_once_with(profile_name='test-profile', region_name='eu-west-1')
            self.assertEqual(repository.table_name, 'test-table')
            self.assertIs(repository.client, session.return_value.client.return_value)

    def test_no_profile_uses_default_credential_chain_for_roles(self):
        settings = self.settings({'CUSTOMER_REPOSITORY': 'dynamodb', 'DYNAMODB_CUSTOMERS_TABLE': 'test-table'})
        with patch('boto3.Session') as session:
            build_repository(settings)
            session.assert_called_once_with(profile_name=None, region_name='eu-west-1')

    def test_invalid_mode_and_missing_table_fail_clearly(self):
        for environment in [{'CUSTOMER_REPOSITORY': 'invalid'}, {'CUSTOMER_REPOSITORY': 'dynamodb'}]:
            with self.subTest(environment=environment), self.assertRaises(ValueError):
                self.settings(environment)

    def test_bad_profile_does_not_silently_fall_back_to_memory(self):
        settings = self.settings({'CUSTOMER_REPOSITORY': 'dynamodb', 'DYNAMODB_CUSTOMERS_TABLE': 'test-table', 'AWS_PROFILE': 'missing'})
        with patch('boto3.Session', side_effect=ProfileNotFound(profile='missing')), self.assertRaises(StorageUnavailable):
            build_repository(settings)
