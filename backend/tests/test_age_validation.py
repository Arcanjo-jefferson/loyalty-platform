import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo
from pydantic import ValidationError
from app.models import CustomerInput


class AgeValidationTests(unittest.TestCase):
    def validate_on(self, today, birth_date):
        with patch('app.models.datetime') as clock:
            clock.now.return_value = datetime.fromisoformat(today).replace(tzinfo=ZoneInfo('Europe/Dublin'))
            return CustomerInput(first_name='Test', last_name='Customer', phone='0871234567', date_of_birth=birth_date)

    def test_exact_eighteenth_birthday(self):
        self.assertEqual(self.validate_on('2026-09-29', '2008-09-29').date_of_birth.isoformat(), '2008-09-29')

    def test_eighteenth_birthday_tomorrow(self):
        with self.assertRaisesRegex(ValidationError, 'Customer must be at least 18 years old.'):
            self.validate_on('2026-09-29', '2008-09-30')

    def test_leap_birthday(self):
        with self.assertRaisesRegex(ValidationError, 'Customer must be at least 18 years old.'):
            self.validate_on('2026-02-28', '2008-02-29')
        self.validate_on('2026-03-01', '2008-02-29')
        self.validate_on('2024-02-29', '2006-02-28')
        with self.assertRaises(ValidationError):
            self.validate_on('2024-02-29', '2006-03-01')

    def test_future_and_invalid_dates(self):
        with self.assertRaisesRegex(ValidationError, 'future'):
            self.validate_on('2026-09-29', '2026-09-30')
        for value in ['2000-02-30', '2001-02-29', 'not-a-date']:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.validate_on('2026-09-29', value)
