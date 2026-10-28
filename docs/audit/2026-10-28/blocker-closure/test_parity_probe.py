"""Eigene synthetische Daten: keine Produktionspfade oder Appimporte."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

import duckdb

from parity_probe import (bag_add,bag_summary,compare,compare_bags,packed,read_connection,
                          snapshot,v2_semantic)


KEY=b"synthetic-test-key-only-not-a-real-evidence-key"


class SemanticTests(unittest.TestCase):
    def test_equal_counts_changed_content_is_detected(self):
        a,b=Counter(),Counter()
        bag_add(a,KEY,{'quantity':Decimal('1')})
        bag_add(b,KEY,{'quantity':Decimal('2')})
        result=compare_bags(bag_summary(a,KEY),bag_summary(b,KEY))
        self.assertEqual(result['left_count'],result['right_count'])
        self.assertFalse(result['equal'])
        self.assertEqual(result['common_rows'],0)

    def test_multiset_retains_duplicates_ignores_row_order(self):
        a,b=Counter(),Counter()
        for row in ['a','b','a']: bag_add(a,KEY,row)
        for row in ['b','a','a']: bag_add(b,KEY,row)
        self.assertTrue(compare_bags(bag_summary(a,KEY),bag_summary(b,KEY))['equal'])
        bag_add(b,KEY,'a')
        self.assertFalse(compare_bags(bag_summary(a,KEY),bag_summary(b,KEY))['equal'])

    def test_decimal_precision_and_utc(self):
        self.assertEqual(packed(Decimal('1.000')),packed(Decimal('1')))
        self.assertNotEqual(packed(Decimal('1.000000000000000000000000000001')),packed(Decimal('1')))
        self.assertNotEqual(packed(Decimal('1')),packed('1'))
        self.assertEqual(packed(datetime(2024,1,1)),packed(datetime(2024,1,1,tzinfo=timezone.utc)))

    def test_event_and_origin_identity_never_dropped(self):
        row={'lot_id':'technical-lot','source_event_id':'original-event-A',
             'origin_lot_id':'origin-A','asset':'SYNTH','quantity_total':Decimal('1')}
        a=v2_semantic('tax_lots',row,{})
        b=v2_semantic('tax_lots',dict(row,lot_id='new-technical-lot'),{})
        self.assertEqual(a,b)
        self.assertNotEqual(a,v2_semantic('tax_lots',dict(row,source_event_id='original-event-B'),{}))
        self.assertNotEqual(a,v2_semantic('tax_lots',dict(row,origin_lot_id='origin-B'),{}))

    def test_tax_line_fk_replaced_by_lot_anchor_not_discarded(self):
        row={'tax_line_id':'technical-line','lot_id':'L1','source_event_id':'sale'}
        anchors={'L1':{'source_event_id':'purchase-A'},'L2':{'source_event_id':'purchase-B'},
                 'L3':{'source_event_id':'purchase-A'}}
        a=v2_semantic('tax_lines',row,anchors)
        self.assertEqual(a,v2_semantic('tax_lines',dict(row,tax_line_id='new',lot_id='L3'),anchors))
        self.assertNotEqual(a,v2_semantic('tax_lines',dict(row,lot_id='L2'),anchors))
        self.assertNotEqual(a,v2_semantic('tax_lines',dict(row,lot_id='missing'),anchors))

    def test_price_time_and_source_are_semantic(self):
        row={'price_id':'tech-A','asset':'SYNTH','price_eur':Decimal('1'),
             'priced_at':datetime(2024,1,1),'source':'synthetic-A'}
        a=v2_semantic('price_ledger',row,{})
        self.assertEqual(a,v2_semantic('price_ledger',dict(row,price_id='tech-B'),{}))
        self.assertNotEqual(a,v2_semantic('price_ledger',dict(row,source='synthetic-B'),{}))
        self.assertNotEqual(a,v2_semantic('price_ledger',dict(row,priced_at=datetime(2024,1,2)),{}))


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        parent=Path('/tmp/steuerreport-blockers-20261028-parity-tests')
        parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.directory=tempfile.TemporaryDirectory(dir=parent,prefix='synthetic-')
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)

    def sqlite(self):
        path=self.root/'legacy.db'
        with sqlite3.connect(path) as con:
            con.execute('create table raw_events (unique_event_id text, source_file_id text, row_index integer, payload_json text, created_at_utc text)')
            con.execute('insert into raw_events values (?,?,?,?,?)',('event','source',0,json.dumps({'raw_row':{'Asset':'SYNTH','Amount':'1'}}),'2024-01-01'))
        return path

    def test_sqlite_readonly_rejects_write_and_preserves_file(self):
        path=self.sqlite();before=hashlib.sha256(path.read_bytes()).hexdigest()
        with read_connection(path,'sqlite-v1') as con:
            with self.assertRaises(sqlite3.OperationalError): con.execute('delete from raw_events')
        self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertFalse(Path(str(path)+'-wal').exists())

    def test_sqlite_snapshots_are_consistent_and_not_engine_equivalence(self):
        path=self.sqlite();a=snapshot(path,'sqlite-v1',KEY);b=snapshot(path,'sqlite-v1',KEY)
        report=compare(a,b)
        self.assertTrue(report['inputs_equal_proven'])
        self.assertFalse(report['engine_parity_proven'])
        self.assertEqual(report['dimensions']['lots']['status'],'unavailable_not_equal_to_empty')
        self.assertEqual(a['projections']['raw_original_payloads']['count'],1)

    def test_duckdb_readonly_and_semantic_line_id_normalization(self):
        path=self.root/'v2.duckdb'
        with duckdb.connect(str(path)) as con:
            con.execute('create table tax_lines (tax_line_id varchar, asset varchar, quantity decimal(38,18), acquired_at timestamp, disposed_at timestamp, acquisition_cost_eur decimal(38,18), disposal_proceeds_eur decimal(38,18), gain_loss_eur decimal(38,18), source_event_id varchar, acquisition_source_event_id varchar, lot_id varchar)')
            con.execute("insert into tax_lines values ('tech-A','SYNTH',1,'2024-01-01','2024-01-02',10,11,1,'sale','purchase',null)")
        first=snapshot(path,'duckdb-v2',KEY)
        with read_connection(path,'duckdb-v2') as con:
            with self.assertRaises(duckdb.Error): con.execute('delete from tax_lines')
        with duckdb.connect(str(path)) as con:
            con.execute("update tax_lines set tax_line_id='tech-B'")
        second=snapshot(path,'duckdb-v2',KEY)
        self.assertNotEqual(first['tables']['tax_lines']['strict'],second['tables']['tax_lines']['strict'])
        self.assertEqual(first['tables']['tax_lines']['semantic'],second['tables']['tax_lines']['semantic'])
        with duckdb.connect(str(path)) as con:
            con.execute('update tax_lines set gain_loss_eur=2')
        third=snapshot(path,'duckdb-v2',KEY)
        self.assertNotEqual(second['tables']['tax_lines']['semantic'],third['tables']['tax_lines']['semantic'])

    def test_archive_byte_change_is_detected(self):
        path=self.root/'v2.duckdb'
        duckdb.connect(str(path)).close()
        archive=self.root/'tax_filing_archive';archive.mkdir()
        file=archive/'synthetic.zip';file.write_bytes(b'fixture-archive-A')
        a=snapshot(path,'duckdb-v2',KEY)
        file.write_bytes(b'fixture-archive-B')
        b=snapshot(path,'duckdb-v2',KEY)
        self.assertNotEqual(a['archive_file_bag'],b['archive_file_bag'])

    def test_missing_database_not_created(self):
        path=self.root/'missing.duckdb'
        with self.assertRaises(FileNotFoundError):
            snapshot(path,'duckdb-v2',KEY)
        self.assertFalse(path.exists())


if __name__=='__main__': unittest.main()
