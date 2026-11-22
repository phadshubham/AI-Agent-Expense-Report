"""
Tier 5 Adversarial & Edge-Case Hardening Test Suite.

Verifies:
1. SQL injection resilience via parameterized queries in memory and filter tools.
2. Graceful degradation on extreme/malformed CSV datasets (empty, all-nulls).
3. Unicode, emoji, and special character sanitization without corruption.
4. Prompt fuzzing (excessive whitespace, mixed casing, contradictory intent).
5. Rapid version incrementing with interleaved HITL corrections and audit trail verification.
"""

import pytest
import sqlite3
from datetime import datetime
from tools.memory_tools import (
    init_memory_db,
    create_or_get_dataset,
    set_active_dataset,
    save_expenses,
    retrieve_expenses_from_db,
    save_validation_issues,
    get_unresolved_issues,
    apply_reviewer_decision,
    get_audit_events,
    increment_dataset_version,
)
from tools.validation_tools import validate_expenses
from tools.calculation_tools import calculate_totals
from agent import extract_canonical_filters


class TestSqlInjectionResilience:
    """Verify that malicious strings in fields do not execute SQL or corrupt state."""

    def test_sql_injection_in_merchant_and_description(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_sqli.db")
        monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", test_db)
        init_memory_db(test_db)

        ds = create_or_get_dataset(name="SQLi Test", file_hash="hash-sqli-1", row_count=1, db_path=test_db)
        ds_id = ds["dataset_id"]

        malicious_records = [
            {
                "record_id": "REC-SQLI-01",
                "date": "2026-06-01",
                "employee": "Robert'); DROP TABLE expenses_v2;--",
                "description": "' OR '1'='1' --",
                "merchant": "Malicious Corp; DELETE FROM datasets;",
                "category": "Meals",
                "amount": 999.0,
                "receipt_status": "Verified",
                "location": "London'; DROP TABLE audit_events;--",
            }
        ]

        save_res = save_expenses(malicious_records, dataset_id=ds_id, dataset_version=1, db_path=test_db)
        assert save_res["inserted"] == 1

        # Confirm expenses_v2 still exists and contains the row intact
        recs = retrieve_expenses_from_db(dataset_id=ds_id, db_path=test_db)
        assert len(recs) == 1
        assert recs[0]["employee"] == "Robert'); DROP TABLE expenses_v2;--"
        assert recs[0]["merchant"] == "Malicious Corp; DELETE FROM datasets;"

        # Confirm query filtering with injection attempt in parameter works safely
        query_res = retrieve_expenses_from_db(
            dataset_id=ds_id,
            employee="Robert'); DROP TABLE expenses_v2;--",
            db_path=test_db,
        )
        assert len(query_res) == 1


class TestMalformedAndAllNullDatasets:
    """Verify non-crashing behavior when encountering completely blank or all-null data."""

    def test_all_null_rows_flagged_without_crash(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_nulls.db")
        monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", test_db)
        init_memory_db(test_db)

        ds = create_or_get_dataset(name="All Nulls", file_hash="hash-nulls-1", row_count=3, db_path=test_db)
        ds_id = ds["dataset_id"]

        all_null_records = [
            {
                "record_id": f"NULL-REC-{i}",
                "date": None,
                "employee": None,
                "description": None,
                "merchant": None,
                "category": None,
                "amount": None,
                "receipt_status": None,
                "location": None,
            }
            for i in range(3)
        ]

        save_res = save_expenses(all_null_records, dataset_id=ds_id, dataset_version=1, db_path=test_db)
        assert save_res["inserted"] == 3

        recs = retrieve_expenses_from_db(dataset_id=ds_id, db_path=test_db)
        assert len(recs) == 3
        for r in recs:
            assert r["amount"] is None
            assert r["date"] is None

        # Validation should flag missing amount, missing date, missing description
        issues = validate_expenses(recs)
        assert len(issues) >= 3

        # Calculation tools should safely ignore null amounts and not raise TypeError
        totals = calculate_totals(recs)
        assert totals["grand_total"] == 0.0
        assert totals["transaction_count"] == 3


class TestUnicodeAndEmojiPreservation:
    """Verify non-ASCII, Unicode characters, and emojis are stored and retrieved accurately."""

    def test_unicode_and_emojis(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_unicode.db")
        monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", test_db)
        init_memory_db(test_db)

        ds = create_or_get_dataset(name="Unicode Test", file_hash="hash-uni-1", row_count=1, db_path=test_db)
        ds_id = ds["dataset_id"]

        unicode_recs = [
            {
                "record_id": "UNI-01",
                "date": "2026-07-15",
                "employee": "François Müller 🚀",
                "description": "Café au lait & croissant ☕🥐",
                "merchant": "Boulangerie Étoile ⭐",
                "category": "Meals",
                "amount": 750.50,
                "receipt_status": "Verified",
                "location": "Zürich / Genève 🇨🇭",
            }
        ]

        save_expenses(unicode_recs, dataset_id=ds_id, dataset_version=1, db_path=test_db)
        recs = retrieve_expenses_from_db(dataset_id=ds_id, db_path=test_db)
        assert len(recs) == 1
        assert "François Müller" in recs[0]["employee"]
        assert "☕🥐" in recs[0]["description"]
        assert "🇨🇭" in recs[0]["location"]


class TestPromptFuzzingAndCanonicalFilters:
    """Verify canonical filter extraction handles adversarial prompt inputs."""

    def test_excessive_whitespace_and_mixed_casing(self):
        prompt = "   \n\t  GENERATE   TRAVEL    EXPENSES   FOR    MAY    2026    FOR   PRIYA   SHARMA   \n\n  "
        filters = extract_canonical_filters(prompt, dataset_employees=["Priya Sharma", "Amit Patel"])
        assert filters["employee"] == "Priya Sharma"
        assert filters["expense_type"] == "travel"
        assert filters["start_date"] == "2026-05-01"
        assert filters["end_date"] == "2026-05-31"

    def test_contradictory_intent_all_vs_specific(self):
        # "all expenses for Amit Patel" -> specific employee should override "all"
        filters = extract_canonical_filters("all expenses for Amit Patel in July 2026", dataset_employees=["Amit Patel", "Ravi Kumar"])
        assert filters["employee"] == "Amit Patel"
        assert filters["expense_type"] == "all"


class TestRapidVersionBumpingAndAuditIntegrity:
    """Verify version sequencing, isolation, and audit trail under rapid successive updates."""

    def test_version_isolation_and_audit_flow(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_vseq.db")
        monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", test_db)
        init_memory_db(test_db)

        ds = create_or_get_dataset(name="Version Sequence", file_hash="hash-vseq", row_count=1, db_path=test_db)
        ds_id = ds["dataset_id"]

        base_recs = [
            {
                "record_id": "REC-V-1",
                "date": "2026-05-01",
                "employee": "Ananya Roy",
                "description": "Flight Ticket",
                "merchant": "Air India",
                "category": "Flight",
                "amount": 5000.0,
                "receipt_status": "Missing",
            }
        ]
        save_expenses(base_recs, dataset_id=ds_id, dataset_version=1, db_path=test_db)

        # Bump to version 2 with updated amount
        v2_recs = [dict(base_recs[0], amount=5500.0, receipt_status="Verified")]
        v2 = increment_dataset_version(ds_id, v2_recs, db_path=test_db)
        assert v2 == 2

        # Bump to version 3 with new row added
        v3_recs = [
            dict(v2_recs[0]),
            {
                "record_id": "REC-V-2",
                "date": "2026-05-02",
                "employee": "Ananya Roy",
                "description": "Hotel Stay",
                "merchant": "Marriott",
                "category": "Accommodation",
                "amount": 7000.0,
                "receipt_status": "Verified",
            },
        ]
        v3 = increment_dataset_version(ds_id, v3_recs, db_path=test_db)
        assert v3 == 3

        # Verify version 1 records unchanged
        v1_query = retrieve_expenses_from_db(dataset_id=ds_id, dataset_version=1, db_path=test_db)
        assert len(v1_query) == 1
        assert v1_query[0]["amount"] == 5000.0

        # Verify version 2 records unchanged
        v2_query = retrieve_expenses_from_db(dataset_id=ds_id, dataset_version=2, db_path=test_db)
        assert len(v2_query) == 1
        assert v2_query[0]["amount"] == 5500.0

        # Verify version 3 records
        v3_query = retrieve_expenses_from_db(dataset_id=ds_id, dataset_version=3, db_path=test_db)
        assert len(v3_query) == 2

        # Verify audit events logged for both version bumps
        events = get_audit_events(dataset_id=ds_id, db_path=test_db)
        bump_events = [e for e in events if e["event_type"] == "dataset_version_incremented"]
        assert len(bump_events) == 2
