import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from contactly_agent.printer import SimulationPrinter, WindowsPrinter
from contactly_agent.transport import HTTPTransport
from contactly_agent.worker import Journal, Worker, simulate


def job(kind='DAILY_RAFFLE', identity=None):
    return dict(print_job_id=identity or kind, source_visit_id='visit', created_at='2026-10-08T12:00:00Z',
                ticket_type=kind, claim_token='x'*43, ticket=dict(receipt_columns=42, receipt_text='Trumps\n€10 Voucher\nCODE-ORIGINAL\n'))

class Transport:
    def __init__(self, jobs): self.queue=jobs; self.calls=[]; self.fail=None; self.claimed=set()
    def jobs(self):
        if self.fail == 'network': raise OSError('Disconnected')
        if self.fail == 'auth': raise HTTPError('url',401,'Unauthorized',{},None)
        return self.queue
    def action(self, identity, action, token=None):
        self.calls.append(action)
        if self.fail == action: raise OSError('Lost reply')
        if action == 'claim':
            if identity in self.claimed: raise HTTPError('url',409,'Conflict',{},None)
            self.claimed.add(identity)
            return next(j for j in self.queue if j['print_job_id']==identity)
        return {}

class Printer:
    def __init__(self): self.output=[]; self.offline=False; self.crash=False
    def prepare(self, job):
        if self.offline: raise OSError('Offline')
        return job['ticket']['receipt_text']
    def submit(self, job, payload):
        self.output.append((job['ticket_type'],payload,'cut'))
        if self.crash: raise SystemExit('Process crash after submission')
        return len(self.output)

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.journal=Journal(self.path/'journal.sqlite3'); self.addCleanup(self.journal.close)
        self.transport=Transport([job()]); self.printer=Printer()
        self.worker=Worker(self.transport,self.printer,self.journal)
    def test_single_raffle_submission_is_not_physical_completion(self):
        self.worker.once()
        self.assertEqual(self.transport.calls,['claim','renew','start','submitted'])
        self.assertEqual(len(self.printer.output),1)
        self.assertNotIn('complete',self.transport.calls)
    def test_separate_ordered_tickets_and_cuts(self):
        self.transport.queue=[job('BIRTHDAY_20'),job('LOYALTY_10'),job()]
        self.worker.once()
        self.assertEqual([x[0] for x in self.printer.output],['DAILY_RAFFLE','LOYALTY_10','BIRTHDAY_20'])
        self.assertTrue(all(x[2]=='cut' for x in self.printer.output))
    def test_simulation_exact_files_no_network_or_windows(self):
        fixture=self.path/'fixture.json'; fixture.write_text(json.dumps([job()]))
        with patch('contactly_agent.transport.HTTPTransport',side_effect=AssertionError()), patch('contactly_agent.printer.WindowsPrinter',side_effect=AssertionError()):
            simulate(fixture,self.path); simulate(fixture,self.path)
        outputs=list((self.path/'simulated').glob('*.txt'))
        self.assertEqual(len(outputs),1); self.assertEqual(outputs[0].read_text(),job()['ticket']['receipt_text'])
        self.assertEqual(self.transport.calls,[])
    def test_offline_preflight_no_start_and_bounded_backend_retry(self):
        self.printer.offline=True; self.worker.once()
        self.assertEqual(self.transport.calls,['claim','fail']); self.assertFalse(self.printer.output)
    def test_network_and_auth_failures_no_output(self):
        for failure in ['network','auth']:
            self.transport.fail=failure
            with self.assertRaises(Exception): self.worker.once()
        self.assertFalse(self.printer.output)
    def test_expired_fence_renewal_no_output(self):
        self.transport.fail='renew'
        with self.assertRaises(OSError): self.worker.once()
        self.assertFalse(self.printer.output)
    def test_lost_start_reply_durable_fence(self):
        self.transport.fail='start'
        with self.assertRaises(OSError): self.worker.once()
        self.transport.fail=None; self.worker.once()
        self.assertFalse(self.printer.output)
        self.assertTrue(self.journal.contains('DAILY_RAFFLE'))
    def test_crash_after_spool_restart_cannot_duplicate(self):
        self.printer.crash=True
        with self.assertRaises(SystemExit): self.worker.once()
        self.printer.crash=False
        other=Journal(self.path/'journal.sqlite3')
        try: Worker(self.transport,self.printer,other).once()
        finally: other.close()
        self.assertEqual(len(self.printer.output),1)
    def test_ack_network_loss_never_reprints(self):
        self.transport.fail='submitted'
        with self.assertRaises(OSError): self.worker.once()
        self.worker.once(); self.assertEqual(len(self.printer.output),1)
    def test_two_agents_atomic_claim_winner_only(self):
        other=Journal(self.path/'other.sqlite3')
        try:
            self.worker.once(); Worker(self.transport,self.printer,other).once()
        finally: other.close()
        self.assertEqual(len(self.printer.output),1)
    def test_explicit_reprint_is_separate_exact_content(self):
        original=job(); reprint=job(identity='original.Rrequest'); reprint['ticket']['receipt_text']='REPRINT\n'+original['ticket']['receipt_text']
        self.transport.queue=[reprint]; self.worker.once()
        self.assertEqual(self.printer.output[0][1],reprint['ticket']['receipt_text'])
        self.assertIn('CODE-ORIGINAL',self.printer.output[0][1])
    def test_production_transport_rejected(self):
        for url in ['https://example.com/development/print-agent','http://localhost:8000/print-jobs','http://user:pass@localhost/development/print-agent']:
            with self.assertRaises(ValueError): HTTPTransport(url)
    def test_http_device_secret_timeout_and_auth_error(self):
        captured=[]
        def opener(request,timeout):
            captured.append((request,timeout)); raise HTTPError('url',401,'Unauthorized',{},None)
        with patch.dict(os.environ,{'CONTACTLY_AGENT_DEV_SECRET':'z'*32}):
            transport=HTTPTransport('http://127.0.0.1:8000/development/print-agent',7,opener)
            with self.assertRaises(HTTPError): transport.jobs()
        self.assertEqual(captured[0][1],7)
        self.assertEqual(captured[0][0].get_header('Authorization'),'Bearer '+'z'*32)
    def test_real_adapter_raw_submission_and_cut(self):
        class API:
            def OpenPrinter(self,name): self.name=name; return 1
            def GetPrinter(self,*args): return {'Status':0}
            def ClosePrinter(self,*args): pass
            def StartDocPrinter(self,*args): self.doc=args; return 77
            def StartPagePrinter(self,*args): pass
            def WritePrinter(self,handle,payload): self.payload=payload; return len(payload)
            def EndPagePrinter(self,*args): pass
            def EndDocPrinter(self,*args): pass
        api=API(); printer=WindowsPrinter('Business installed queue',api)
        payload=printer.prepare(job()); self.assertEqual(printer.submit(job(),payload),77)
        self.assertEqual(api.name,'Business installed queue'); self.assertEqual(api.doc[2][2],'RAW')
        self.assertTrue(api.payload.endswith(b'\x1dVB\x00'))
    def test_unsupported_encoding_fails_before_output(self):
        value=job(); value['ticket']['receipt_text']='漢字'
        with self.assertRaises(UnicodeEncodeError): WindowsPrinter('test',object()).prepare(value)

    def test_lease_renewed_during_slow_submission(self):
        import time
        submit=self.printer.submit
        def slow(job,payload): time.sleep(0.03); return submit(job,payload)
        self.printer.submit=slow
        with patch('contactly_agent.worker.RENEW_SECONDS',0.005): self.worker.once()
        self.assertGreaterEqual(self.transport.calls.count('renew'),2)

    def test_concurrent_agents_only_one_outputs(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        barrier=threading.Barrier(2); lock=threading.Lock()
        original_jobs=self.transport.jobs; original_action=self.transport.action
        def jobs(): result=original_jobs(); barrier.wait(); return result
        def action(*args):
            with lock: return original_action(*args)
        self.transport.jobs=jobs; self.transport.action=action
        def run(number):
            journal=Journal(self.path/('agent'+str(number)+'.sqlite3'))
            try: Worker(self.transport,self.printer,journal).once()
            finally: journal.close()
        with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(run,[1,2]))
        self.assertEqual(len(self.printer.output),1)

    def test_redirects_cannot_forward_device_secret(self):
        from contactly_agent.transport import NoRedirect
        with self.assertRaises(ValueError): NoRedirect().redirect_request(None,None,302,'',{},'https://other.example')

    def test_shutdown_does_not_process_more_jobs(self):
        Worker(self.transport,self.printer,self.journal,lambda:True).once()
        self.assertFalse(self.transport.calls)
