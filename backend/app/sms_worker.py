"""Lifecycle-managed, SIMULATION-ONLY outbox worker. No provider network transport.
Only verified human business scopes or explicit server configuration enter the set.
The DynamoDB outbox is authoritative; UNKNOWN submissions are never requeued.
"""
import logging
import re
from threading import Event, Lock, Thread
from .sms_provider import require_worker_provider


class SMSWorker:
    def __init__(self, service, businesses=(), interval=2):
        self.service = service
        self.interval = interval
        self.businesses = set()
        self.lock = Lock()
        self.wakeup = Event()
        self.stopping = Event()
        self.thread = None
        for business in businesses: self.notify(business)

    def notify(self, business):
        if not isinstance(business, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', business):
            raise ValueError('Invalid SMS worker business configuration.')
        with self.lock: self.businesses.add(business)
        self.wakeup.set()

    def tick(self):
        # Deliberate fail-closed barrier: adding a real adapter requires separate approval.
        require_worker_provider(self.service.provider)
        with self.lock: businesses = sorted(self.businesses)
        for business in businesses:
            if self.stopping.is_set(): break
            try:
                self.service.process(business, limit=20, should_stop=self.stopping.is_set)
            except Exception:
                logging.getLogger('loyalty.sms').warning('sms_simulation_worker_unavailable')

    def _run(self):
        while not self.stopping.is_set():
            self.wakeup.clear()
            try: self.tick()
            except Exception:
                # No provider exception, recipient, message, credentials or tenant in logs.
                logging.getLogger('loyalty.sms').warning('sms_simulation_worker_unavailable')
            self.wakeup.wait(self.interval)

    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stopping.clear()
        self.thread = Thread(target=self._run, name='sms-simulation-worker', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.wakeup.set()
        if self.thread: self.thread.join()
