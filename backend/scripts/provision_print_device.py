"""OPERATOR tooling: bind an already provisioned/verified confidential M2M client.
No Cognito resources are created or changed. No secrets are accepted or displayed.
Dry-run by default. Run only after verifying client credentials ONLY grant, allowed
custom scope, token TTL, issuer and unique per-device ownership in the provider.
"""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import Settings, build_repository
from app.print_devices import DeviceRegistry


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--business',required=True)
    parser.add_argument('--device-id',required=True)
    parser.add_argument('--client-id',required=True)
    parser.add_argument('--provider-verified',action='store_true')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    settings=Settings.from_environment()
    if settings.customer_repository!='dynamodb': parser.error('Persistent device provisioning requires DynamoDB.')
    registry=DeviceRegistry(build_repository(settings))
    device=registry.get(args.business,args.device_id)
    if device['status']!='PENDING_PROVISIONING': parser.error('Device must be pending provisioning.')
    print('Bind existing confidential client to pending device; no provider changes or credentials involved.')
    if not args.apply:
        print('DRY RUN: no writes. Add --apply --provider-verified after external verification.'); return
    if not args.provider_verified: parser.error('--provider-verified is required before activation.')
    registry.activate(args.business,args.device_id,args.client_id,'operator:provisioning')
    print('Device activated. Store its separately delivered secret only in Windows Credential Manager.')

if __name__=='__main__': main()
