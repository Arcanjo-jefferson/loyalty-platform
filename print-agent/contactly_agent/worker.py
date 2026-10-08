"""Durable local output fence plus server CAS. Never retry started/uncertain output."""
import json
import logging
from pathlib import Path
import sqlite3
import threading
from urllib.error import HTTPError

RENEW_SECONDS = 30

ORDER = {'DAILY_RAFFLE': 0, 'LOYALTY_10': 1, 'BIRTHDAY_20': 2}
log = logging.getLogger('contactly.agent')

class Journal:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS output (job TEXT PRIMARY KEY, state TEXT, spool TEXT)')
        self.db.commit()
    def reserve(self, job):
        try:
            with self.db: self.db.execute('INSERT INTO output VALUES (?, ?, NULL)', (job, 'START_INTENT'))
            return True
        except sqlite3.IntegrityError: return False
    def submitted(self, job, spool):
        with self.db: self.db.execute('UPDATE output SET state=?, spool=? WHERE job=?', ('SUBMITTED', str(spool), job))
    def contains(self, job): return self.db.execute('SELECT 1 FROM output WHERE job=?', (job,)).fetchone() is not None
    def close(self): self.db.close()

class Worker:
    def __init__(self, transport, printer, journal, stopped=lambda: False):
        self.transport, self.printer, self.journal = transport, printer, journal
        self.stopped = stopped
    def once(self):
        jobs = sorted(self.transport.jobs(), key=lambda j: (j['created_at'], j['source_visit_id'], ORDER[j['ticket_type']], j['print_job_id']))
        for summary in jobs:
            if self.stopped(): return
            identity = summary['print_job_id']
            if self.journal.contains(identity):
                log.warning(json.dumps({'event': 'local_output_fence', 'physical_output': 'unknown'}))
                continue
            try: job = self.transport.action(identity, 'claim')
            except HTTPError as error:
                if error.code == 409: continue  # Another agent won the atomic claim.
                raise
            token = job['claim_token']
            try: payload = self.printer.prepare(job)
            except Exception:
                self.transport.action(identity, 'fail', token)
                log.warning(json.dumps({'event': 'preflight_failed'}))
                continue
            # Renew after slow preflight; stale/expired fence prevents any output.
            self.transport.action(identity, 'renew', token)
            if not self.journal.reserve(identity): continue
            # Persist intent BEFORE start. A lost start reply or crash cannot cause retry.
            self.transport.action(identity, 'start', token)
            heartbeat_stop = threading.Event()
            def renew_lease():
                while not heartbeat_stop.wait(RENEW_SECONDS):
                    try: self.transport.action(identity, 'renew', token)
                    except Exception:
                        log.warning(json.dumps({'event': 'lease_renewal_failed', 'physical_output': 'unknown'}))
                        return
            heartbeat = threading.Thread(target=renew_lease, daemon=True)
            heartbeat.start()
            try:
                try: spool = self.printer.submit(job, payload)
                finally:
                    heartbeat_stop.set()
                    heartbeat.join()
                self.journal.submitted(identity, spool)
                self.transport.action(identity, 'submitted', token)
                log.info(json.dumps({'event': 'spool_accepted', 'physical_output': 'unconfirmed'}))
            except Exception:
                # Even an OpenPrinter failure after START is conservatively uncertain.
                try: self.transport.action(identity, 'fail', token)
                except Exception: pass  # Expired PRINTING becomes UNCERTAIN on backend reads.
                raise

def simulate(fixture, directory):
    from .printer import SimulationPrinter
    printer = SimulationPrinter(Path(directory) / 'simulated')
    with open(fixture, encoding='utf-8') as stream: jobs = json.load(stream)
    for job in sorted(jobs, key=lambda j: (j['created_at'], j['source_visit_id'], ORDER[j['ticket_type']])):
        try: printer.submit(job, printer.prepare(job))
        except FileExistsError: pass
    # No network transport is constructed and no lifecycle API is called.
