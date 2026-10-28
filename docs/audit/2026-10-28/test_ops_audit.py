"""Eigene synthetische Datenbanken, keine Verbindung zur Produktion."""
import datetime
import decimal
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

import duckdb

import ops_restore
import ops_snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".ops-test-", dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "data.duckdb"
        self.env = patch.dict(os.environ, {"STEUERREPORT_STATE_DIR": str(self.root),
                                          "STEUERREPORT_V2_DB": str(self.path)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def execute(self, sql):
        with duckdb.connect(str(self.path)) as con:
            con.execute(sql)

    def test_full_tables_and_duplicate_sensitive_order_independent_hash(self):
        self.execute("create table t (i int, value varchar); insert into t values (1,'x'),(2,'y'),(1,'x'); "
                     "create table empty_table (i integer)")
        before = ops_snapshot.snapshot()
        self.assertEqual(set(before["tables"]), {"main.t", "main.empty_table"})
        self.execute("delete from t; insert into t values (2,'y'),(1,'x'),(1,'x')")
        self.assertEqual(before["tables"], ops_snapshot.snapshot()["tables"])
        self.execute("delete from t where i=2")
        self.assertNotEqual(before["tables"]["main.t"], ops_snapshot.snapshot()["tables"]["main.t"])

    def test_same_row_count_content_change_detected(self):
        self.execute("create table t (i int); insert into t values (1)")
        before = ops_snapshot.snapshot()
        self.execute("update t set i=2")
        after = ops_snapshot.snapshot()
        self.assertEqual(before["tables"]["main.t"]["rows"], after["tables"]["main.t"]["rows"])
        self.assertNotEqual(before["tables"]["main.t"]["sha256"], after["tables"]["main.t"]["sha256"])

    def test_readonly_snapshot_preserves_database_and_private_files(self):
        self.execute("create table t (i int)")
        secret = self.root / "synthetic-key"
        secret.write_bytes(b"SYNTHETIC_ONLY_NOT_A_REAL_KEY")
        before = self.path.read_bytes()
        snapshot = ops_snapshot.snapshot()
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(set(snapshot["files"]), {"synthetic-key"})
        self.assertNotIn("SYNTHETIC_ONLY", json.dumps(snapshot))

    def test_types_are_not_lossily_coerced(self):
        values = [decimal.Decimal("1.2300"), datetime.datetime(2024, 2, 29),
                  datetime.date(2024, 2, 29), datetime.time(1, 2), b"x", uuid.UUID(int=1)]
        self.assertNotEqual(ops_snapshot.packed(values[0]), ops_snapshot.packed("1.2300"))
        for value in values:
            self.assertEqual(ops_snapshot.packed(value), ops_snapshot.packed(value))


class GuardTests(unittest.TestCase):
    def test_ownership_guard_rejects_foreign_resources(self):
        with patch.object(ops_restore, "inspect", return_value={"Labels": {ops_restore.LABEL: "other"}}):
            self.assertFalse(ops_restore.owned("volume", "test", "ours"))
        with patch.object(ops_restore, "inspect", return_value={"Config": {"Labels": {ops_restore.LABEL: "ours"}}}):
            self.assertTrue(ops_restore.owned("container", "test", "ours"))

    def test_private_evidence_exclusive_and_mode600(self):
        with tempfile.TemporaryDirectory(prefix=".ops-test-", dir=Path(__file__).parent) as directory:
            root = Path(directory)
            ops_restore.write_private(root, "proof.json", {"test": True})
            self.assertEqual((root / "proof.json").stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                ops_restore.write_private(root, "proof.json", {"test": False})

    def test_failed_command_does_not_echo_private_stdout_or_stderr(self):
        import subprocess
        failed = subprocess.CompletedProcess(["docker"], 1, "SYNTHETIC_PRIVATE", "SYNTHETIC_PRIVATE")
        with patch.object(ops_restore.subprocess, "run", return_value=failed):
            with self.assertRaises(RuntimeError) as caught:
                ops_restore.command(["docker", "inspect", "dummy"])
        self.assertNotIn("SYNTHETIC_PRIVATE", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
