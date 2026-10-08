import argparse
import json
import logging
from pathlib import Path
import signal
import threading
from .worker import Worker, Journal, simulate
from .printer import WindowsPrinter
from .transport import HTTPTransport


def main():
    parser = argparse.ArgumentParser(description='Contactly test print agent; simulation by default')
    parser.add_argument('--config', default='config.example.json')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text(encoding='utf-8'))
    base = config_path.parent
    directory = base / config.get('state_directory', 'state')
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(message)s', handlers=[logging.StreamHandler(), logging.FileHandler(directory / 'agent.log', encoding='utf-8')])
    mode = config.get('mode', 'simulation')
    if mode == 'simulation':
        simulate(base / config.get('fixture', 'tickets.example.json'), directory)
        return
    if mode != 'development-windows' or config.get('allow_development_printing') is not True:
        raise ValueError('Production transport is blocked. Explicit isolated development printing opt-in required.')
    interval = float(config.get('poll_seconds', 3))
    timeout = float(config.get('timeout_seconds', 10))
    if not 1 <= interval <= 60 or not 1 <= timeout <= 30: raise ValueError('Invalid polling/HTTP timeout.')
    transport = HTTPTransport(config['backend_url'], timeout)
    printer = WindowsPrinter(config['printer_name'])
    journal = Journal(directory / 'output.sqlite3')
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, lambda *_: stop.set())
    worker = Worker(transport, printer, journal, stop.is_set)
    backoff = interval
    try:
        while not stop.is_set():
            try:
                worker.once()
                backoff = interval
            except Exception:
                # Never log server body, ticket PII, credentials or exception text.
                logging.error(json.dumps({'event': 'worker_failed', 'action': 'reconnect_or_operator_review'}))
                backoff = min(30, max(interval, backoff * 2))
            if args.once: break
            stop.wait(backoff)
    finally: journal.close()

if __name__ == '__main__': main()
