"""Canonical tenant-scoped PRINT# jobs; customer/visit prefixes, no Scan or GSI."""
import json
from uuid import uuid4
from pydantic import ValidationError
from botocore.exceptions import BotoCoreError, ClientError
from .print_models import PrintJob, PrintJobNotFound, PrintJobConflict
from .repository import StorageUnavailable


def print_key(job_id): return 'PRINT#' + job_id


def guard_transaction(actions):
    # Conservative wire-size bound exceeds stored attribute size; fail before writing.
    wire_size = len(json.dumps(actions, ensure_ascii=True).encode())
    existing_item_reserve = sum(400 * 1024 for action in actions if 'Update' in action or 'ConditionCheck' in action)
    if len(actions) > 100 or wire_size + existing_item_reserve >= 4 * 1024 * 1024:
        raise StorageUnavailable()
    for action in actions:
        if 'Put' in action and len(json.dumps(action['Put']['Item'], ensure_ascii=True).encode()) >= 400 * 1024:
            raise StorageUnavailable()


class DynamoPrintMixin:
    def _print_item(self, job):
        return {**job.model_dump(mode='json'), 'customer_id': print_key(job.print_job_id),
                'owner_customer_id': job.customer_id, 'item_type': 'PRINT_JOB'}

    def _print_job(self, item):
        if not item or item.get('item_type') != 'PRINT_JOB': raise PrintJobNotFound()
        try:
            return PrintJob.model_validate({**{name: item[name] for name in PrintJob.model_fields if name in item},
                                            'customer_id': item['owner_customer_id']})
        except (ValidationError, KeyError, TypeError) as exc: raise StorageUnavailable() from exc

    def _print_put(self, job):
        return {'Put': {'TableName': self.table_name, 'Item': self._encode(self._print_item(job)),
                        'ConditionExpression': 'attribute_not_exists(#pk)', 'ExpressionAttributeNames': {'#pk': 'business_id'}}}

    def get_print_job(self, business_id, job_id):
        job = self._print_job(self._read_item(business_id, print_key(job_id)))
        if job.business_id != business_id or job.print_job_id != job_id: raise StorageUnavailable()
        return job

    def print_jobs(self, business_id, customer_id=None, visit_id=None):
        prefix = 'PRINT#' + (customer_id + '.' if customer_id else '') + (visit_id + '.' if visit_id and customer_id else '')
        params = {'TableName': self.table_name,
                  'KeyConditionExpression': '#business = :business AND begins_with(#sk, :prefix)',
                  'ExpressionAttributeNames': {'#business': 'business_id', '#sk': 'customer_id'},
                  'ExpressionAttributeValues': self._encode({':business': business_id, ':prefix': prefix}), 'ConsistentRead': True}
        jobs = []
        while True:
            page = self._call('query', **params)
            for raw in page.get('Items', []):
                item = self._decode(raw); job = self._print_job(item)
                if (job.business_id != business_id or item['customer_id'] != print_key(job.print_job_id)
                        or (customer_id and job.customer_id != customer_id) or (visit_id and job.source_visit_id != visit_id)):
                    raise StorageUnavailable()
                jobs.append(job)
            if not page.get('LastEvaluatedKey'): return sorted(jobs, key=lambda job: (job.created_at, job.print_job_id), reverse=True)
            params['ExclusiveStartKey'] = page['LastEvaluatedKey']

    def _print_check(self, job):
        return {'TableName': self.table_name, 'Key': self._key(job.business_id, print_key(job.print_job_id)),
                'ConditionExpression': '#kind = :kind AND #revision = :revision',
                'ExpressionAttributeNames': {'#kind': 'item_type', '#revision': 'revision'},
                'ExpressionAttributeValues': self._encode({':kind': 'PRINT_JOB', ':revision': job.revision})}

    def _print_update(self, previous, updated):
        # Update lifecycle fields only; immutable snapshot/source cannot be replaced.
        fields = ['status', 'updated_at', 'attempt_count', 'printed_at', 'last_error', 'claim_token', 'claimed_by', 'lease_until', 'revision', 'audit']
        action = self._print_check(previous)
        data = updated.model_dump(mode='json')
        action['UpdateExpression'] = 'SET ' + ', '.join(f'#f{i} = :f{i}' for i in range(len(fields)))
        action['ExpressionAttributeNames'].update({f'#f{i}': field for i, field in enumerate(fields)})
        action['ExpressionAttributeValues'].update(self._encode({f':f{i}': data[field] for i, field in enumerate(fields)}))
        return {'Update': action}

    def save_print_change(self, previous, updated):
        self._print_transaction([self._print_update(previous, updated)])

    def save_reprint(self, original, updated, job):
        self._print_transaction([self._print_update(original, updated), self._print_put(job)])

    def _print_transaction(self, actions):
        guard_transaction(actions)
        try: self.client.transact_write_items(TransactItems=actions, ClientRequestToken=str(uuid4()))
        except ClientError as exc:
            if exc.response.get('Error', {}).get('Code') in {'TransactionCanceledException', 'TransactionConflictException'}:
                raise PrintJobConflict('Job changed. Refresh before trying again.') from exc
            raise StorageUnavailable() from exc
        except BotoCoreError as exc: raise StorageUnavailable() from exc
