"""Explicit installed Windows queue; no default/settings/driver mutation APIs."""
from pathlib import Path
import hashlib
import os
from .formatting import receipt_text

class SimulationPrinter:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
    def prepare(self, job): return receipt_text(job).encode('utf-8')
    def submit(self, job, payload):
        name = hashlib.sha256(job['print_job_id'].encode()).hexdigest() + '.txt'
        target = self.directory / name
        # Exact immutable content, one file/ticket, no printer module imported.
        with target.open('xb') as stream: stream.write(payload)
        return name

class WindowsPrinter:
    def __init__(self, name, api=None):
        if not name: raise ValueError('An explicit installed printer name is required.')
        if api is None:
            if os.name != 'nt': raise RuntimeError('Real printing requires Windows.')
            import win32print
            api = win32print
        self.name, self.api = name, api
    def prepare(self, job):
        text = receipt_text(job)
        columns = job['ticket']['receipt_columns']
        if columns != 42 or any(len(line) > columns for line in text.splitlines()):
            raise ValueError('Unsupported receipt width; immutable content cannot be truncated.')
        if any(ord(ch) < 32 and ch != '\n' for ch in text):
            raise ValueError('Unsafe receipt control character.')
        # Strict encoding: unsupported names fail before output, never silently corrupt.
        payload = b'\x1b@\x1bt\x13' + text.encode('cp858') + b'\n\n\x1dVB\x00'
        handle = self.api.OpenPrinter(self.name)
        try:
            info = self.api.GetPrinter(handle, 2)
            # Conservative: paused/offline/error/paper/attention status => pre-output failure.
            if info.get('Status', 0): raise RuntimeError('Printer requires attention.')
        finally: self.api.ClosePrinter(handle)
        return payload
    def submit(self, job, payload):
        api = self.api
        handle = api.OpenPrinter(self.name)
        try:
            spool_id = api.StartDocPrinter(handle, 1, ('Contactly ticket', None, 'RAW'))
            api.StartPagePrinter(handle)
            if api.WritePrinter(handle, payload) != len(payload):
                raise RuntimeError('Incomplete spool submission; output uncertain.')
            api.EndPagePrinter(handle)
            api.EndDocPrinter(handle)
            return spool_id
        finally: api.ClosePrinter(handle)
