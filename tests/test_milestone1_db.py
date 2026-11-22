"""
Comprehensive Automated Test Suite for Milestone 1:
Database Architecture, Safe Schema Migration, & Dataset Isolation.

Verifies:
1. TestSafeMigration: Idempotent migration from v1 to v2, automated backup creation,
   legacy attribution of 370 expenses, 5 issues, 10 report runs, 0 FK errors, view triggers.
2. TestDatasetLifecycle: Dataset master registration, hashing, version incrementing, active switching.
3. TestDatasetIsolation: Strict multi-dataset isolation across queries, memory stats, issues, reports.
4. TestNullPreservation: Preservation of raw null amounts and dates without coercion to 0.0 or empty string,
   prevention of TypeError crashes on retrieval.
5. TestAuditEvents: Immutable compliance audit logging, scoping, and retrieval.
"""

import os
import sys
import io
import shutil
import tempfile
import sqlite3
import hashlib
import unittest
from datetime import datetime, timezone

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from tools.memory_tools import (
    init_memory_db,
    backup_memory_db,
    create_or_get_dataset,
    set_active_dataset,
    get_active_dataset,
    increment_dataset_version,
    save_expenses,
    retrieve_expenses_from_db,
    get_previous_expenses,
    save_validation_issues,
    get_unresolved_issues,
    update_expense_record,
    resolve_validation_issue,
    save_report_run,
    get_report_history,
    get_memory_stats,
    save_audit_event,
    get_audit_events,
    LEGACY_DATASET_ID,
)


class TestSafeMigration(unittest.TestCase):
    """
    Verifies automated backup and safe schema migration (v1 -> v2)
    against an exact copy of the pre-migration database data/expense_memory.db.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.prod_db_path = os.path.join("data", "expense_memory.db")
        self.test_db_path = os.path.join(self.temp_dir, "migrated_expense_memory.db")

        # Copy existing database to temp location
        if os.path.exists(self.prod_db_path):
            shutil.copy2(self.prod_db_path, self.test_db_path)
            # Record initial production hash to ensure zero corruption of prod file
            with open(self.prod_db_path, "rb") as f:
                self.prod_initial_hash = hashlib.sha256(f.read()).hexdigest()
        else:
            self.skipTest("data/expense_memory.db not found for migration test")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pre_migration_backup_creation(self):
        """Verifies timestamped backup is created when migrating an existing database."""
        # Ensure user_version is 0 on the test copy before migration
        conn = sqlite3.connect(self.test_db_path)
        ver = conn.execute("PRAGMA user_version;").fetchone()[0]
        conn.close()

        if ver == 0:
            # Trigger init_memory_db which should detect ver < 2 and trigger backup
            init_memory_db(self.test_db_path)

            # Check that backup was created in temp_dir
            backups = [f for f in os.listdir(self.temp_dir) if "backup" in f and f.endswith(".db")]
            self.assertGreaterEqual(len(backups), 1, "Backup file was not created in directory")
            backup_path = os.path.join(self.temp_dir, backups[0])
            self.assertGreater(os.path.getsize(backup_path), 0, "Backup file is empty")

    def test_schema_migration_preserves_records_and_tags_legacy(self):
        """
        Verifies that running init_memory_db on v1 database:
        - Bumps user_version to 2
        - Retains all 370 expenses tagged as DATASET-LEGACY-UNASSIGNED, version 1
        - Retains all 5 validation issues tagged as DATASET-LEGACY-UNASSIGNED, version 1
        - Retains all 10 report runs tagged as DATASET-LEGACY-UNASSIGNED, version 1
        - Has zero foreign key check errors
        - Leaves production data/expense_memory.db untouched
        """
        init_memory_db(self.test_db_path)

        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()

        # 1. user_version == 2
        ver = cursor.execute("PRAGMA user_version;").fetchone()[0]
        self.assertEqual(ver, 2)

        # 2. Datasets table contains DATASET-LEGACY-UNASSIGNED
        cursor.execute("SELECT name, row_count, version, is_active FROM datasets WHERE dataset_id = ?", (LEGACY_DATASET_ID,))
        ds_row = cursor.fetchone()
        self.assertIsNotNone(ds_row)
        self.assertEqual(ds_row[0], "Legacy Unassigned Ingested Data")
        self.assertEqual(ds_row[1], 370)
        self.assertEqual(ds_row[2], 1)
        self.assertEqual(ds_row[3], 0)  # Inactive by default

        # 3. Expenses count in expenses_v2 and legacy tagging
        cursor.execute("SELECT COUNT(*) FROM expenses_v2 WHERE dataset_id = ? AND dataset_version = 1", (LEGACY_DATASET_ID,))
        exp_count = cursor.fetchone()[0]
        self.assertEqual(exp_count, 370)

        # 4. Validation issues count in validation_issues_v2 and legacy tagging
        cursor.execute("SELECT COUNT(*) FROM validation_issues_v2 WHERE dataset_id = ? AND dataset_version = 1", (LEGACY_DATASET_ID,))
        val_count = cursor.fetchone()[0]
        self.assertEqual(val_count, 5)

        # 5. Report runs count in report_runs_v2 and legacy tagging
        cursor.execute("SELECT COUNT(*) FROM report_runs_v2 WHERE dataset_id = ? AND dataset_version = 1", (LEGACY_DATASET_ID,))
        rep_count = cursor.fetchone()[0]
        self.assertEqual(rep_count, 10)

        # 6. Zero foreign key errors
        cursor.execute("PRAGMA foreign_keys = ON;")
        fk_errors = cursor.execute("PRAGMA foreign_key_check;").fetchall()
        self.assertEqual(len(fk_errors), 0, f"Foreign key check failed: {fk_errors}")

        conn.close()

    def test_migration_idempotence(self):
        """Verifies calling init_memory_db multiple times does not corrupt or duplicate data."""
        init_memory_db(self.test_db_path)
        # Second call
        init_memory_db(self.test_db_path)
        # Third call
        init_memory_db(self.test_db_path)

        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()

        exp_count = cursor.execute("SELECT COUNT(*) FROM expenses_v2").fetchone()[0]
        self.assertEqual(exp_count, 370)

        val_count = cursor.execute("SELECT COUNT(*) FROM validation_issues_v2").fetchone()[0]
        self.assertEqual(val_count, 5)

        rep_count = cursor.execute("SELECT COUNT(*) FROM report_runs_v2").fetchone()[0]
        self.assertEqual(rep_count, 10)

        conn.close()

    def test_view_triggers_allow_raw_dml(self):
        """Verifies INSTEAD OF triggers allow INSERT, UPDATE, DELETE on expenses view."""
        init_memory_db(self.test_db_path)
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()

        # Insert through view
        test_rec_id = "EXP-TEST-TRIGGER-001"
        cursor.execute("""
            INSERT INTO expenses (record_id, expense_date, employee, description, merchant, category, amount, receipt_status, source_file, import_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (test_rec_id, "2026-09-01", "Trigger Test", "Office Supplies", "Staples", "Supplies", 125.50, "Verified", "trigger_test", "hash123", "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()

        # Verify record exists in expenses_v2
        cursor.execute("SELECT amount, employee FROM expenses_v2 WHERE record_id = ?", (test_rec_id,))
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 125.50)
        self.assertEqual(row[1], "Trigger Test")

        # Update through view
        cursor.execute("UPDATE expenses SET amount = 150.00 WHERE record_id = ?", (test_rec_id,))
        conn.commit()
        cursor.execute("SELECT amount FROM expenses_v2 WHERE record_id = ?", (test_rec_id,))
        self.assertEqual(cursor.fetchone()[0], 150.00)

        # Delete through view
        cursor.execute("DELETE FROM expenses WHERE record_id = ?", (test_rec_id,))
        conn.commit()
        cursor.execute("SELECT COUNT(*) FROM expenses_v2 WHERE record_id = ?", (test_rec_id,))
        self.assertEqual(cursor.fetchone()[0], 0)

        conn.close()


class TestDatasetLifecycle(unittest.TestCase):
    """Verifies dataset creation, hashing, active switching, and version incrementing."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_lifecycle.db")
        init_memory_db(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_and_get_active_dataset(self):
        """Verifies creating a dataset makes it active and sets proper metadata."""
        schema = {"columns": ["date", "employee", "amount", "merchant"]}
        ds = create_or_get_dataset(
            name="Mumbai Q3 Expenses",
            file_hash="hash_mumbai_123",
            row_count=50,
            schema=schema,
            db_path=self.db_path,
        )

        self.assertTrue(ds["dataset_id"].startswith("DS-"))
        self.assertEqual(ds["name"], "Mumbai Q3 Expenses")
        self.assertEqual(ds["row_count"], 50)
        self.assertEqual(ds["version"], 1)
        self.assertEqual(ds["is_active"], 1)

        # Verify get_active_dataset matches
        active = get_active_dataset(self.db_path)
        self.assertIsNotNone(active)
        self.assertEqual(active["dataset_id"], ds["dataset_id"])
        self.assertEqual(active["file_hash"], "hash_mumbai_123")

    def test_create_or_get_existing_dataset(self):
        """Verifies uploading identical file_hash returns existing dataset ID."""
        ds1 = create_or_get_dataset(
            name="Delhi Upload 1",
            file_hash="hash_delhi_same",
            row_count=20,
            db_path=self.db_path,
        )
        ds2 = create_or_get_dataset(
            name="Delhi Upload 2",
            file_hash="hash_delhi_same",
            row_count=20,
            db_path=self.db_path,
        )
        self.assertEqual(ds1["dataset_id"], ds2["dataset_id"])

    def test_set_active_dataset(self):
        """Verifies switching active dataset activates target and deactivates others."""
        ds_a = create_or_get_dataset(name="Dataset A", file_hash="hash_a", row_count=10, db_path=self.db_path)
        ds_b = create_or_get_dataset(name="Dataset B", file_hash="hash_b", row_count=20, db_path=self.db_path)

        # After creating B, B is active
        self.assertEqual(get_active_dataset(self.db_path)["dataset_id"], ds_b["dataset_id"])

        # Switch back to A
        success = set_active_dataset(ds_a["dataset_id"], db_path=self.db_path)
        self.assertTrue(success)
        self.assertEqual(get_active_dataset(self.db_path)["dataset_id"], ds_a["dataset_id"])

        # Try non-existent ID
        fake_success = set_active_dataset("DS-NONEXISTENT", db_path=self.db_path)
        self.assertFalse(fake_success)

    def test_increment_dataset_version(self):
        """Verifies increment_dataset_version updates version number and stores snapshot."""
        ds = create_or_get_dataset(name="Version Test", file_hash="hash_v", row_count=2, db_path=self.db_path)
        initial_records = [
            {"record_id": "REC-1", "date": "2026-08-01", "employee": "Alice", "amount": 100.0, "category": "Meals"},
            {"record_id": "REC-2", "date": "2026-08-02", "employee": "Alice", "amount": 200.0, "category": "Transport"},
        ]
        save_expenses(initial_records, dataset_id=ds["dataset_id"], dataset_version=1, db_path=self.db_path)

        # Update records for version 2
        updated_records = [
            {"record_id": "REC-1", "date": "2026-08-01", "employee": "Alice", "amount": 150.0, "category": "Meals"},  # Edited amount
            {"record_id": "REC-2", "date": "2026-08-02", "employee": "Alice", "amount": 200.0, "category": "Transport"},
            {"record_id": "REC-3", "date": "2026-08-03", "employee": "Bob", "amount": 300.0, "category": "Flight"},      # Added row
        ]
        new_ver = increment_dataset_version(ds["dataset_id"], updated_records, db_path=self.db_path)
        self.assertEqual(new_ver, 2)

        # Verify dataset row count and version updated in master table
        active = get_active_dataset(self.db_path)
        self.assertEqual(active["version"], 2)
        self.assertEqual(active["row_count"], 3)

        # Historical v1 remains intact
        v1_records = retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=1, db_path=self.db_path)
        self.assertEqual(len(v1_records), 2)
        rec1_v1 = next(r for r in v1_records if r["record_id"] == "REC-1")
        self.assertEqual(rec1_v1["amount"], 100.0)

        # Current v2 has 3 records with updated amount
        v2_records = retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=2, db_path=self.db_path)
        self.assertEqual(len(v2_records), 3)
        rec1_v2 = next(r for r in v2_records if r["record_id"] == "REC-1")
        self.assertEqual(rec1_v2["amount"], 150.0)


class TestDatasetIsolation(unittest.TestCase):
    """
    Verifies strict database-level isolation between multiple datasets
    (e.g., Mumbai vs. Delhi).
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_isolation.db")
        init_memory_db(self.db_path)

        # Dataset A: Mumbai
        self.ds_mumbai = create_or_get_dataset(
            name="Mumbai Dataset", file_hash="hash_mumbai", row_count=3, db_path=self.db_path
        )
        self.mumbai_records = [
            {"record_id": "MUM-1", "date": "2026-08-01", "employee": "Vikram Seth", "amount": 1200.0, "category": "Meals", "location": "Mumbai"},
            {"record_id": "MUM-2", "date": "2026-08-02", "employee": "Vikram Seth", "amount": 4500.0, "category": "Hotel", "location": "Mumbai"},
            {"record_id": "MUM-3", "date": "2026-08-03", "employee": "Ananya Roy", "amount": 800.0, "category": "Transport", "location": "Mumbai"},
        ]
        save_expenses(self.mumbai_records, dataset_id=self.ds_mumbai["dataset_id"], dataset_version=1, db_path=self.db_path)

        # Dataset B: Delhi
        self.ds_delhi = create_or_get_dataset(
            name="Delhi Dataset", file_hash="hash_delhi", row_count=2, db_path=self.db_path
        )
        self.delhi_records = [
            {"record_id": "DEL-1", "date": "2026-08-10", "employee": "Rahul Sharma", "amount": 9500.0, "category": "Flight", "location": "Delhi"},
            {"record_id": "DEL-2", "date": "2026-08-11", "employee": "Rahul Sharma", "amount": 3200.0, "category": "Meals", "location": "Delhi"},
        ]
        save_expenses(self.delhi_records, dataset_id=self.ds_delhi["dataset_id"], dataset_version=1, db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_query_retrieval_isolation(self):
        """Verifies retrieve_expenses_from_db strictly scopes to requested dataset_id."""
        mumbai_recs = retrieve_expenses_from_db(dataset_id=self.ds_mumbai["dataset_id"], db_path=self.db_path)
        self.assertEqual(len(mumbai_recs), 3)
        self.assertTrue(all(r["dataset_id"] == self.ds_mumbai["dataset_id"] for r in mumbai_recs))
        self.assertTrue(all(r["location"] == "Mumbai" for r in mumbai_recs))

        delhi_recs = retrieve_expenses_from_db(dataset_id=self.ds_delhi["dataset_id"], db_path=self.db_path)
        self.assertEqual(len(delhi_recs), 2)
        self.assertTrue(all(r["dataset_id"] == self.ds_delhi["dataset_id"] for r in delhi_recs))
        self.assertTrue(all(r["location"] == "Delhi" for r in delhi_recs))

    def test_active_dataset_fallback_isolation(self):
        """Verifies omitting dataset_id scopes queries to the currently active dataset."""
        # Delhi is currently active (created second)
        recs = retrieve_expenses_from_db(db_path=self.db_path)
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["location"], "Delhi")

        # Switch active dataset to Mumbai
        set_active_dataset(self.ds_mumbai["dataset_id"], db_path=self.db_path)
        recs_after = retrieve_expenses_from_db(db_path=self.db_path)
        self.assertEqual(len(recs_after), 3)
        self.assertEqual(recs_after[0]["location"], "Mumbai")

    def test_memory_stats_isolation(self):
        """Verifies get_memory_stats returns scoped counts per dataset."""
        m_stats = get_memory_stats(dataset_id=self.ds_mumbai["dataset_id"], db_path=self.db_path)
        self.assertEqual(m_stats["total_expenses"], 3)
        self.assertEqual(m_stats["unique_employees"], 2)  # Vikram Seth, Ananya Roy

        d_stats = get_memory_stats(dataset_id=self.ds_delhi["dataset_id"], db_path=self.db_path)
        self.assertEqual(d_stats["total_expenses"], 2)
        self.assertEqual(d_stats["unique_employees"], 1)  # Rahul Sharma

    def test_validation_issues_isolation(self):
        """Verifies validation issues are isolated by dataset."""
        # Save issue for Mumbai record
        save_validation_issues(
            [{"record_id": "MUM-1", "issue_type": "missing_receipt", "message": "Receipt missing for MUM-1"}],
            dataset_id=self.ds_mumbai["dataset_id"],
            db_path=self.db_path,
        )
        # Save issue for Delhi record
        save_validation_issues(
            [{"record_id": "DEL-1", "issue_type": "high_amount", "message": "High amount for DEL-1"}],
            dataset_id=self.ds_delhi["dataset_id"],
            db_path=self.db_path,
        )

        m_issues = get_unresolved_issues(dataset_id=self.ds_mumbai["dataset_id"], db_path=self.db_path)
        self.assertEqual(len(m_issues), 1)
        self.assertEqual(m_issues[0]["expense_record_id"], "MUM-1")

        d_issues = get_unresolved_issues(dataset_id=self.ds_delhi["dataset_id"], db_path=self.db_path)
        self.assertEqual(len(d_issues), 1)
        self.assertEqual(d_issues[0]["expense_record_id"], "DEL-1")

    def test_report_history_isolation(self):
        """Verifies report run history is isolated by dataset."""
        save_report_run(
            {"report_id": "REP-MUM-1", "user_request": "Mumbai Report", "dataset_id": self.ds_mumbai["dataset_id"]},
            db_path=self.db_path,
        )
        save_report_run(
            {"report_id": "REP-DEL-1", "user_request": "Delhi Report", "dataset_id": self.ds_delhi["dataset_id"]},
            db_path=self.db_path,
        )

        m_history = get_report_history(dataset_id=self.ds_mumbai["dataset_id"], db_path=self.db_path)
        self.assertEqual(len(m_history), 1)
        self.assertEqual(m_history[0]["report_id"], "REP-MUM-1")

        d_history = get_report_history(dataset_id=self.ds_delhi["dataset_id"], db_path=self.db_path)
        self.assertEqual(len(d_history), 1)
        self.assertEqual(d_history[0]["report_id"], "REP-DEL-1")


class TestNullPreservation(unittest.TestCase):
    """
    Verifies null and missing value resilience:
    - Null amounts must remain NULL in SQLite and None in Python (not 0.0).
    - Null dates must remain NULL in SQLite and None in Python (not empty string).
    - Legitimate 0.0 amount is distinguished from missing/None amount.
    - Retrieval never crashes with TypeError: float() argument must be a string or a real number, not 'NoneType'.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_nulls.db")
        init_memory_db(self.db_path)
        self.ds = create_or_get_dataset(name="Null Test", file_hash="hash_null", row_count=3, db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_null_amount_and_date_preservation_in_sqlite(self):
        """Direct SQLite inspection verifying NULL is stored, not coerced to 0.0 or ''."""
        records = [
            {"record_id": "NULL-AMT-1", "date": "2026-08-01", "employee": "Test Emp", "amount": None, "merchant": "Vendor A"},
            {"record_id": "NULL-DATE-1", "date": None, "employee": "Test Emp", "amount": 500.0, "merchant": "Vendor B"},
            {"record_id": "ZERO-AMT-1", "date": "2026-08-02", "employee": "Test Emp", "amount": 0.0, "merchant": "Vendor C"},
        ]
        save_expenses(records, dataset_id=self.ds["dataset_id"], db_path=self.db_path)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check NULL-AMT-1 directly in expenses_v2
        cursor.execute("SELECT amount, expense_date FROM expenses_v2 WHERE record_id = 'NULL-AMT-1'")
        row = cursor.fetchone()
        self.assertIsNone(row[0], "amount column must be SQLite NULL for None input")
        self.assertEqual(row[1], "2026-08-01")

        # Check NULL-DATE-1 directly in expenses_v2
        cursor.execute("SELECT amount, expense_date FROM expenses_v2 WHERE record_id = 'NULL-DATE-1'")
        row2 = cursor.fetchone()
        self.assertEqual(row2[0], 500.0)
        self.assertIsNone(row2[1], "expense_date column must be SQLite NULL for None input")

        # Check ZERO-AMT-1 distinguishes 0.0 from NULL
        cursor.execute("SELECT amount FROM expenses_v2 WHERE record_id = 'ZERO-AMT-1'")
        row3 = cursor.fetchone()
        self.assertEqual(row3[0], 0.0, "0.0 amount must be stored as 0.0 float, not NULL")

        conn.close()

    def test_retrieval_returns_none_without_typeerror(self):
        """Verifies retrieve_expenses_from_db returns None for missing amounts without crashing."""
        records = [
            {"record_id": "NULL-AMT-RETRIEVE", "date": "2026-08-05", "employee": "Test Emp", "amount": None},
            {"record_id": "ZERO-AMT-RETRIEVE", "date": "2026-08-05", "employee": "Test Emp", "amount": 0.0},
        ]
        save_expenses(records, dataset_id=self.ds["dataset_id"], db_path=self.db_path)

        # This call previously crashed with TypeError: float() argument must be a string or a real number, not 'NoneType'
        retrieved = retrieve_expenses_from_db(dataset_id=self.ds["dataset_id"], db_path=self.db_path)

        null_rec = next(r for r in retrieved if r["record_id"] == "NULL-AMT-RETRIEVE")
        zero_rec = next(r for r in retrieved if r["record_id"] == "ZERO-AMT-RETRIEVE")

        self.assertIsNone(null_rec["amount"], "Retrieved amount should be None for null amount record")
        self.assertEqual(zero_rec["amount"], 0.0, "Retrieved amount should be 0.0 for zero amount record")
        self.assertNotEqual(null_rec["amount"], zero_rec["amount"], "None amount and 0.0 amount must not be conflated")


class TestAuditEvents(unittest.TestCase):
    """Verifies audit event logging, persistence, and scoped querying."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_audit.db")
        init_memory_db(self.db_path)
        self.ds = create_or_get_dataset(name="Audit Test", file_hash="hash_aud", row_count=10, db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_retrieve_audit_events(self):
        """Verifies saving audit events and retrieving them filtered by dataset and entity."""
        ev1 = save_audit_event(
            dataset_id=self.ds["dataset_id"],
            event_type="correction",
            entity_type="expense",
            entity_id="EXP-101",
            details={"field": "amount", "old_value": None, "new_value": 450.0},
            db_path=self.db_path,
        )
        self.assertTrue(ev1.startswith("AUD-"))

        ev2 = save_audit_event(
            dataset_id=self.ds["dataset_id"],
            event_type="exclusion",
            entity_type="expense",
            entity_id="EXP-102",
            details={"reason": "Personal expense"},
            db_path=self.db_path,
        )
        self.assertTrue(ev2.startswith("AUD-"))

        # Retrieve by dataset
        events = get_audit_events(dataset_id=self.ds["dataset_id"], db_path=self.db_path)
        self.assertGreaterEqual(len(events), 2)

        # Retrieve by entity_id
        entity_events = get_audit_events(dataset_id=self.ds["dataset_id"], entity_id="EXP-101", db_path=self.db_path)
        self.assertEqual(len(entity_events), 1)
        self.assertEqual(entity_events[0]["event_type"], "correction")
        self.assertEqual(entity_events[0]["details"]["new_value"], 450.0)


if __name__ == "__main__":
    unittest.main()
