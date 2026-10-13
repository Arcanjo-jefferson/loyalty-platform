import copy
import json
from pathlib import Path
import unittest
from contactly_agent.formatting import receipt_text
from contactly_agent.printer import SimulationPrinter, WindowsPrinter
import tempfile

class TicketTimeTests(unittest.TestCase):
    def fixtures(self): return json.loads((Path(__file__).resolve().parents[1]/'tickets.example.json').read_text())
    def test_all_three_fixture_types_original_date_hour_and_width(self):
        fixtures=self.fixtures()
        self.assertEqual({j['ticket_type'] for j in fixtures},{'DAILY_RAFFLE','LOYALTY_10','BIRTHDAY_20'})
        with tempfile.TemporaryDirectory() as folder:
            printer=SimulationPrinter(folder)
            for job in fixtures:
                original=copy.deepcopy(job)
                text=receipt_text(job)
                self.assertIn('Issued date: 08/10/2026',text)
                self.assertIn('Issued time: 13:00',text.splitlines())
                self.assertTrue(all(len(line)<=42 for line in text.splitlines()))
                payload=printer.prepare(job); name=printer.submit(job,payload)
                self.assertEqual((Path(folder)/name).read_text(),text)
                self.assertEqual(job,original)
    def test_dst_midnight_conversion_and_winter(self):
        for instant,date,hour in [('2026-10-06T23:55:00Z','07/10/2026','00:55'),('2026-01-06T23:55:00Z','06/01/2026','23:55'),('2026-03-29T01:05:00Z','29/03/2026','02:05'),('2026-10-25T01:05:00Z','25/10/2026','01:05')]:
            job=self.fixtures()[0]
            job['ticket'].update(issued_at=instant,receipt_text=f'Issued date: {date}\nIssued time: {hour}\nEurope/Dublin')
            self.assertEqual(receipt_text(job),job['ticket']['receipt_text'])
    def test_retry_reprint_preserves_original_timestamp_not_new_job_time(self):
        job=self.fixtures()[1]; original=copy.deepcopy(job['ticket'])
        job['created_at']='2030-01-01T00:00:00Z'
        self.assertEqual(receipt_text(job),original['receipt_text'])
        job['reprint_of']='original'; job['ticket']['receipt_text']='REPRINT\n'+original['receipt_text']
        self.assertEqual(receipt_text(job),'REPRINT\n'+original['receipt_text'])
        self.assertEqual(job['ticket']['issued_at'],original['issued_at'])
    def test_bad_or_naive_issue_and_unlabelled_reprint_rejected_before_printer(self):
        for updates in [dict(issued_at='2026-10-08T12:00:00'),dict(receipt_text='No timestamp'),dict(timezone='UTC')]:
            job=self.fixtures()[0]; job['ticket'].update(updates)
            with self.assertRaises(ValueError): WindowsPrinter('test',object()).prepare(job)
        job=self.fixtures()[0]; job['reprint_of']='original'
        with self.assertRaises(ValueError): receipt_text(job)
    def test_legacy_snapshot_format_remains_immutable(self):
        job=self.fixtures()[0]; job['ticket'].update(template_version=1,receipt_text='Date/time: 08/10/2026 13:00 IST')
        self.assertEqual(receipt_text(job),'Date/time: 08/10/2026 13:00 IST')

    def test_actual_minutes_for_all_three_types_never_rounded_or_clock_based(self):
        for timestamp, expected in [('2026-10-08T08:05:00Z','09:05'),('2026-10-08T12:00:00Z','13:00'),('2026-10-08T16:45:00Z','17:45'),('2026-10-08T22:59:00Z','23:59')]:
            for job in self.fixtures():
                job['created_at']='2035-01-01T00:00:00Z'
                job['ticket'].update(issued_at=timestamp,receipt_text=f'Issued date: 08/10/2026\nIssued time: {expected}\nEurope/Dublin')
                original=job['ticket']['receipt_text']
                self.assertEqual(receipt_text(job),original)
                job['reprint_of']='original'
                job['ticket']['receipt_text']='REPRINT\n'+original
                self.assertEqual(receipt_text(job),'REPRINT\n'+original)
                self.assertTrue(all(len(line)<=42 for line in receipt_text(job).splitlines()))
                job['ticket']['receipt_text']=job['ticket']['receipt_text'].replace(expected,expected[:2]+':00')
                if not expected.endswith(':00'):
                    with self.assertRaises(ValueError): receipt_text(job)

    def test_preexisting_hour_only_snapshot_remains_printable_and_immutable(self):
        job=self.fixtures()[0]
        job['ticket']['template_version']=2
        job['ticket']['receipt_text']=job['ticket']['receipt_text'].replace('13:00','13')
        original=copy.deepcopy(job)
        self.assertEqual(receipt_text(job),original['ticket']['receipt_text'])
        self.assertEqual(job,original)
