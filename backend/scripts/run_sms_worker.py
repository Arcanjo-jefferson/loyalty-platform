"""SIMULATION ONLY. Supervise independently; no Twilio/network sender exists.
Uses the configured repository. Do not run against production or real customers.
An explicit operator-owned business argument selects the partition; no HTTP bypass.
"""
import argparse
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings, build_repository
from app.service import CustomerService
from app.sms_service import SMSService
from app.sms_models import SMSSettings
from app.sms_provider import require_simulation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--business', required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    try: require_simulation(SMSSettings.for_business(args.business).provider)
    except (ValueError, RuntimeError): parser.error('SMS provider is disabled or misconfigured; only simulation is available.')
    config = Settings.from_environment()
    if config.customer_repository != 'dynamodb': parser.error('Standalone worker requires durable DynamoDB storage. Memory mode is processed by the application background simulator.')
    if not args.business or args.business.startswith('!'): parser.error('Use a normal business partition.')
    service = SMSService(CustomerService(build_repository(config)))
    while True:
        result = service.process(args.business)
        print('Simulation batch processed:', result['processed'])
        if args.once: return
        time.sleep(5)


if __name__ == '__main__': main()
