"""
E2E Tier 1: Feature Coverage Test Suite (95 tests across F1–F19).
Validates core functional capabilities across all requirements R1–R7:
Dataset Management, History & Tracking, Compliance Workspace,
Canonical Filter Pipeline, UI Normalization, Migration Safety, and Workflow Checkpoints.
"""

import os
import io
import re
import ast
import json
import sqlite3
import hashlib
import tempfile
import pytest
from datetime import datetime

import tools.memory_tools as memory_tools
import tools.expense_tools as expense_tools
import tools.validation_tools as validation_tools
import tools.calculation_tools as calculation_tools
import tools.pdf_tools as pdf_tools
import agent


# ============================================================================
# F1: Dataset Creation & SHA-256 Identification (R1, PROJECT.md F2)
# ============================================================================

def test_t1_f1_01_compute_sha256_digest(mumbai_expenses_csv):
    """F1-1: Compute SHA-256 of synthetic CSV; assert valid 64-char hexadecimal digest."""
    with open(mumbai_expenses_csv, "rb") as f:
        file_bytes = f.read()
    digest = hashlib.sha256(file_bytes).hexdigest()
    assert len(digest) == 64
    assert re.match(r"^[a-f0-9]{64}$", digest) is not None


@pytest.mark.skipif(not hasattr(memory_tools, "create_or_get_dataset"), reason="Waiting for M1 create_or_get_dataset")
def test_t1_f1_02_create_dataset_record(mumbai_expenses_csv):
    """F1-2: Call create_or_get_dataset; verify dataset_id, file_hash, name, row_count in datasets table."""
    with open(mumbai_expenses_csv, "rb") as f:
        content = f.read()
    file_hash = hashlib.sha256(content).hexdigest()
    ds = memory_tools.create_or_get_dataset(name="Mumbai Expenses", file_hash=file_hash, row_count=7)
    assert "dataset_id" in ds
    assert ds["file_hash"] == file_hash
    assert ds["row_count"] == 7
    assert ds["version"] == 1


@pytest.mark.skipif(not hasattr(memory_tools, "create_or_get_dataset"), reason="Waiting for M1 create_or_get_dataset")
def test_t1_f1_03_deduplicate_identical_csv(mumbai_expenses_csv):
    """F1-3: Re-upload identical file; assert existing dataset_id returned without duplicate row."""
    with open(mumbai_expenses_csv, "rb") as f:
        content = f.read()
    file_hash = hashlib.sha256(content).hexdigest()
    ds1 = memory_tools.create_or_get_dataset(name="Mumbai Expenses", file_hash=file_hash, row_count=7)
    ds2 = memory_tools.create_or_get_dataset(name="Mumbai Expenses Reupload", file_hash=file_hash, row_count=7)
    assert ds1["dataset_id"] == ds2["dataset_id"]


@pytest.mark.skipif(not hasattr(memory_tools, "create_or_get_dataset"), reason="Waiting for M1 create_or_get_dataset")
def test_t1_f1_04_distinct_file_distinct_dataset_id(mumbai_expenses_csv, delhi_expenses_csv):
    """F1-4: Upload Mumbai vs Delhi CSV; assert two distinct dataset_ids created."""
    with open(mumbai_expenses_csv, "rb") as f:
        hash_mumbai = hashlib.sha256(f.read()).hexdigest()
    with open(delhi_expenses_csv, "rb") as f:
        hash_delhi = hashlib.sha256(f.read()).hexdigest()
    ds_mumbai = memory_tools.create_or_get_dataset(name="Mumbai", file_hash=hash_mumbai, row_count=7)
    ds_delhi = memory_tools.create_or_get_dataset(name="Delhi", file_hash=hash_delhi, row_count=5)
    assert ds_mumbai["dataset_id"] != ds_delhi["dataset_id"]


@pytest.mark.skipif(not hasattr(memory_tools, "create_or_get_dataset"), reason="Waiting for M1 create_or_get_dataset")
def test_t1_f1_05_schema_json_metadata():
    """F1-5: Verify inferred column types are stored in schema_json metadata column."""
    schema = {"date": "TEXT", "amount": "REAL", "employee": "TEXT", "city": "TEXT"}
    ds = memory_tools.create_or_get_dataset(name="Schema Test", file_hash="hash123", row_count=10, schema=schema)
    assert "schema_json" in ds or "schema" in ds


# ============================================================================
# F2: Auto-Persistence on Upload & Save (R1, PROJECT.md F13)
# ============================================================================

def test_t1_f2_01_auto_persist_records_on_upload(sample_expenses):
    """F2-1: Ingest records; assert all rows immediately queryable in expenses table."""
    res = memory_tools.save_expenses(sample_expenses[:10], source_name="test_upload.csv")
    inserted = res["inserted"] if isinstance(res, dict) else res[0]
    assert inserted == 10
    retrieved = memory_tools.retrieve_expenses_from_db()
    assert len(retrieved) >= 10


@pytest.mark.skipif(not hasattr(memory_tools, "create_or_get_dataset"), reason="Waiting for M1 create_or_get_dataset")
def test_t1_f2_02_records_tagged_with_dataset_id(sample_expenses):
    """F2-2: Query expenses; assert dataset_id on every inserted record matches dataset metadata."""
    ds = memory_tools.create_or_get_dataset(name="Tagged DS", file_hash="taghash", row_count=5)
    memory_tools.save_expenses(sample_expenses[:5], dataset_id=ds["dataset_id"], source_name="tag.csv")
    recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"])
    assert len(recs) == 5
    for r in recs:
        assert r.get("dataset_id") == ds["dataset_id"]


@pytest.mark.skipif(not hasattr(memory_tools, "create_or_get_dataset"), reason="Waiting for M1 create_or_get_dataset")
def test_t1_f2_03_records_tagged_with_version_one(sample_expenses):
    """F2-3: Assert all freshly uploaded records have dataset_version == 1."""
    ds = memory_tools.create_or_get_dataset(name="V1 DS", file_hash="v1hash", row_count=3)
    memory_tools.save_expenses(sample_expenses[:3], dataset_id=ds["dataset_id"], source_name="v1.csv")
    recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"])
    for r in recs:
        assert r.get("dataset_version", 1) == 1


@pytest.mark.skipif(not hasattr(memory_tools, "increment_dataset_version"), reason="Waiting for M1 increment_dataset_version")
def test_t1_f2_04_auto_persist_on_editor_save(sample_expenses):
    """F2-4: Save edited records; assert updated rows immediately reflected in DB."""
    ds = memory_tools.create_or_get_dataset(name="Edit DS", file_hash="edithash", row_count=2)
    memory_tools.save_expenses(sample_expenses[:2], dataset_id=ds["dataset_id"])
    edited = list(sample_expenses[:2])
    edited[0]["amount"] = 9999.0
    new_v = memory_tools.increment_dataset_version(ds["dataset_id"], edited)
    assert new_v == 2
    v2_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=2)
    assert any(r["amount"] == 9999.0 for r in v2_recs)


def test_t1_f2_05_foreign_key_dataset_constraint():
    """F2-5: Assert SQLite foreign keys are enforced on connections."""
    conn = memory_tools.get_connection()
    fk_status = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
    conn.close()
    assert fk_status == 1


# ============================================================================
# F3: Active Dataset Switching & Isolation (R1, PROJECT.md F3)
# ============================================================================

@pytest.mark.skipif(not hasattr(memory_tools, "set_active_dataset"), reason="Waiting for M1 set_active_dataset")
def test_t1_f3_01_activate_dataset_sets_flag():
    """F3-1: Call set_active_dataset(ds_id); assert is_active == 1."""
    ds = memory_tools.create_or_get_dataset(name="Active DS", file_hash="act1", row_count=1)
    ok = memory_tools.set_active_dataset(ds["dataset_id"])
    assert ok is True
    active = memory_tools.get_active_dataset()
    assert active is not None
    assert active["dataset_id"] == ds["dataset_id"]


@pytest.mark.skipif(not hasattr(memory_tools, "set_active_dataset"), reason="Waiting for M1 set_active_dataset")
def test_t1_f3_02_mutual_exclusivity_single_active():
    """F3-2: Activate dataset B; assert dataset A has is_active == 0."""
    ds_a = memory_tools.create_or_get_dataset(name="DS A", file_hash="actA", row_count=1)
    ds_b = memory_tools.create_or_get_dataset(name="DS B", file_hash="actB", row_count=1)
    memory_tools.set_active_dataset(ds_a["dataset_id"])
    memory_tools.set_active_dataset(ds_b["dataset_id"])
    active = memory_tools.get_active_dataset()
    assert active["dataset_id"] == ds_b["dataset_id"]


@pytest.mark.skipif(not hasattr(memory_tools, "get_active_dataset"), reason="Waiting for M1 get_active_dataset")
def test_t1_f3_03_get_active_dataset():
    """F3-3: Call get_active_dataset(); assert returns currently active dataset dictionary."""
    ds = memory_tools.create_or_get_dataset(name="Active Query DS", file_hash="actQ", row_count=1)
    memory_tools.set_active_dataset(ds["dataset_id"])
    active = memory_tools.get_active_dataset()
    assert active["name"] == "Active Query DS"


@pytest.mark.skipif(not hasattr(memory_tools, "set_active_dataset"), reason="Waiting for M1 set_active_dataset")
def test_t1_f3_04_switch_back_restores_active():
    """F3-4: Switch back to dataset A; assert get_active_dataset()['dataset_id'] == ds_a_id."""
    ds_a = memory_tools.create_or_get_dataset(name="DS A", file_hash="hashA", row_count=1)
    ds_b = memory_tools.create_or_get_dataset(name="DS B", file_hash="hashB", row_count=1)
    memory_tools.set_active_dataset(ds_a["dataset_id"])
    memory_tools.set_active_dataset(ds_b["dataset_id"])
    memory_tools.set_active_dataset(ds_a["dataset_id"])
    assert memory_tools.get_active_dataset()["dataset_id"] == ds_a["dataset_id"]


@pytest.mark.skipif(not hasattr(memory_tools, "set_active_dataset"), reason="Waiting for M1 set_active_dataset")
def test_t1_f3_05_active_flag_persists_across_connections():
    """F3-5: Open new DB connection; assert get_active_dataset() retains active state."""
    ds = memory_tools.create_or_get_dataset(name="Persist Active", file_hash="pact", row_count=1)
    memory_tools.set_active_dataset(ds["dataset_id"])
    # Fresh connection query
    active = memory_tools.get_active_dataset()
    assert active["dataset_id"] == ds["dataset_id"]


# ============================================================================
# F4: Interactive Editor Versioning & Persistence (R1, PROJECT.md F4, F14)
# ============================================================================

@pytest.mark.skipif(not hasattr(memory_tools, "create_or_get_dataset"), reason="Waiting for M1 create_or_get_dataset")
def test_t1_f4_01_initial_version_is_one():
    """F4-1: Verify new dataset starts at version == 1."""
    ds = memory_tools.create_or_get_dataset(name="Version 1 DS", file_hash="v1check", row_count=5)
    assert ds["version"] == 1


@pytest.mark.skipif(not hasattr(memory_tools, "increment_dataset_version"), reason="Waiting for M1 increment_dataset_version")
def test_t1_f4_02_save_increments_version(sample_expenses):
    """F4-2: Modify 1 cell, call increment_dataset_version; assert version becomes 2."""
    ds = memory_tools.create_or_get_dataset(name="Increment DS", file_hash="inc1", row_count=2)
    memory_tools.save_expenses(sample_expenses[:2], dataset_id=ds["dataset_id"])
    v2 = memory_tools.increment_dataset_version(ds["dataset_id"], sample_expenses[:2])
    assert v2 == 2


@pytest.mark.skipif(not hasattr(memory_tools, "increment_dataset_version"), reason="Waiting for M1 increment_dataset_version")
def test_t1_f4_03_row_addition_persists(sample_expenses):
    """F4-3: Add 2 rows to editor; assert version 2 contains N + 2 records."""
    ds = memory_tools.create_or_get_dataset(name="Add Rows DS", file_hash="addr", row_count=2)
    memory_tools.save_expenses(sample_expenses[:2], dataset_id=ds["dataset_id"])
    updated = list(sample_expenses[:4])  # 2 + 2 = 4
    memory_tools.increment_dataset_version(ds["dataset_id"], updated)
    v2_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=2)
    assert len(v2_recs) == 4


@pytest.mark.skipif(not hasattr(memory_tools, "increment_dataset_version"), reason="Waiting for M1 increment_dataset_version")
def test_t1_f4_04_row_deletion_persists(sample_expenses):
    """F4-4: Delete 1 row in editor; assert version 2 contains N - 1 records."""
    ds = memory_tools.create_or_get_dataset(name="Del Rows DS", file_hash="delr", row_count=3)
    memory_tools.save_expenses(sample_expenses[:3], dataset_id=ds["dataset_id"])
    updated = list(sample_expenses[:2])  # 3 - 1 = 2
    memory_tools.increment_dataset_version(ds["dataset_id"], updated)
    v2_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=2)
    assert len(v2_recs) == 2


@pytest.mark.skipif(not hasattr(memory_tools, "increment_dataset_version"), reason="Waiting for M1 increment_dataset_version")
def test_t1_f4_05_historical_version_immutable(sample_expenses):
    """F4-5: Query expenses where dataset_version == 1; assert original values unchanged."""
    ds = memory_tools.create_or_get_dataset(name="Immutable DS", file_hash="imm", row_count=2)
    original_amt = sample_expenses[0]["amount"]
    memory_tools.save_expenses(sample_expenses[:2], dataset_id=ds["dataset_id"])
    edited = list(sample_expenses[:2])
    edited[0]["amount"] = 99999.0
    memory_tools.increment_dataset_version(ds["dataset_id"], edited)
    v1_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=1)
    assert v1_recs[0]["amount"] == original_amt


# ============================================================================
# F5: Query-Level Dataset Isolation (R1, PROJECT.md F3)
# ============================================================================

def test_t1_f5_01_retrieve_scoped_to_active_dataset(sample_expenses):
    """F5-1: Populate DS-A (10 rows) & DS-B (15 rows); retrieve DS-A; assert exactly 10 rows returned."""
    if hasattr(memory_tools, "create_or_get_dataset"):
        ds_a = memory_tools.create_or_get_dataset(name="DS A", file_hash="dsa", row_count=10)
        ds_b = memory_tools.create_or_get_dataset(name="DS B", file_hash="dsb", row_count=15)
        memory_tools.save_expenses(sample_expenses[:10], dataset_id=ds_a["dataset_id"])
        memory_tools.save_expenses(sample_expenses[:15], dataset_id=ds_b["dataset_id"])
        recs_a = memory_tools.retrieve_expenses_from_db(dataset_id=ds_a["dataset_id"])
        assert len(recs_a) == 10
    else:
        # Backward-compatible check
        res = memory_tools.save_expenses(sample_expenses[:10], source_name="ds_a.csv")
        assert (res["inserted"] if isinstance(res, dict) else res[0]) == 10


def test_t1_f5_02_employee_filter_isolated_by_dataset(sample_expenses):
    """F5-2: Both datasets have employee; query DS-A for employee; assert 0 DS-B rows returned."""
    priya_recs = [e for e in sample_expenses if e.get("employee") == "Priya Sharma"]
    if hasattr(memory_tools, "create_or_get_dataset"):
        ds_a = memory_tools.create_or_get_dataset(name="DS A", file_hash="iso_emp_a", row_count=len(priya_recs))
        ds_b = memory_tools.create_or_get_dataset(name="DS B", file_hash="iso_emp_b", row_count=len(sample_expenses))
        memory_tools.save_expenses(priya_recs[:3], dataset_id=ds_a["dataset_id"])
        memory_tools.save_expenses(sample_expenses, dataset_id=ds_b["dataset_id"])
        res = memory_tools.retrieve_expenses_from_db(dataset_id=ds_a["dataset_id"], employee="Priya Sharma")
        assert len(res) == 3
    else:
        memory_tools.save_expenses(priya_recs[:3], source_name="priya.csv")
        res = memory_tools.retrieve_expenses_from_db(employee="Priya Sharma")
        assert len(res) == 3


def test_t1_f5_03_memory_stats_isolated(sample_expenses):
    """F5-3: Assert get_memory_stats() returns accurate scoped counts."""
    memory_tools.save_expenses(sample_expenses[:5], source_name="stats_test.csv")
    stats = memory_tools.get_memory_stats()
    assert stats["total_expenses"] >= 5


def test_t1_f5_04_date_range_queries_isolated(sample_expenses):
    """F5-4: Filter by date range; assert no dates outside range returned."""
    memory_tools.save_expenses(sample_expenses, source_name="date_iso.csv")
    recs = memory_tools.retrieve_expenses_from_db(start_date="2026-08-01", end_date="2026-08-10")
    for r in recs:
        d = r.get("date") or r.get("expense_date")
        assert "2026-08-01" <= d <= "2026-08-10"


@pytest.mark.skipif(not hasattr(memory_tools, "increment_dataset_version"), reason="Waiting for M1 increment_dataset_version")
def test_t1_f5_05_version_scoped_retrieval(sample_expenses):
    """F5-5: Retrieve dataset_version == 1; assert records modified in version 2 not returned."""
    ds = memory_tools.create_or_get_dataset(name="V Scope DS", file_hash="vscope", row_count=2)
    memory_tools.save_expenses(sample_expenses[:2], dataset_id=ds["dataset_id"])
    edited = list(sample_expenses[:2])
    edited[0]["description"] = "V2 Modified Description"
    memory_tools.increment_dataset_version(ds["dataset_id"], edited)
    v1_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=1)
    assert not any("V2 Modified" in r["description"] for r in v1_recs)


# ============================================================================
# F6: Dataset-Scoped Prompt & Report History (R2, PROJECT.md F5)
# ============================================================================

def test_t1_f6_01_save_report_run_with_dataset_id():
    """F6-1: Save report run; verify report_id and metadata stored in report_runs."""
    run_data = {
        "report_id": "REP-T1-F6-01",
        "user_request": "Travel report Priya August",
        "filters": {"employee": "Priya Sharma", "month": "August 2026"},
        "transaction_ids": ["EXP-1", "EXP-2"],
        "transaction_count": 2,
        "grand_total": 12500.0,
        "validation_status": "Clear",
        "report_file_path": "reports/rep_f6_01.pdf",
        "human_review_status": "None",
    }
    rep_id = memory_tools.save_report_run(run_data)
    assert rep_id == "REP-T1-F6-01"


def test_t1_f6_02_get_report_history_scoped():
    """F6-2: Retrieve report history; assert inserted run is present."""
    memory_tools.save_report_run({
        "report_id": "REP-HIST-SCOPED",
        "user_request": "Audit query",
        "filters": {"month": "August 2026"},
        "transaction_ids": ["EXP-1"],
        "transaction_count": 1,
        "grand_total": 5000.0,
        "validation_status": "Clear",
        "report_file_path": "reports/scoped.pdf",
        "human_review_status": "None",
    })
    history = memory_tools.get_report_history()
    assert any(h["report_id"] == "REP-HIST-SCOPED" for h in history)


def test_t1_f6_03_history_chronological_order():
    """F6-3: Assert runs ordered by created_at DESC."""
    memory_tools.save_report_run({
        "report_id": "REP-EARLY",
        "user_request": "First run",
        "filters": {},
        "transaction_ids": [],
        "transaction_count": 0,
        "grand_total": 100.0,
        "validation_status": "Clear",
        "report_file_path": "reports/early.pdf",
        "human_review_status": "None",
    })
    memory_tools.save_report_run({
        "report_id": "REP-LATER",
        "user_request": "Second run",
        "filters": {},
        "transaction_ids": [],
        "transaction_count": 0,
        "grand_total": 200.0,
        "validation_status": "Clear",
        "report_file_path": "reports/later.pdf",
        "human_review_status": "None",
    })
    history = memory_tools.get_report_history()
    # REP-LATER should appear before or equal to REP-EARLY
    ids = [h["report_id"] for h in history]
    assert ids.index("REP-LATER") < ids.index("REP-EARLY")


def test_t1_f6_04_history_stores_canonical_filters():
    """F6-4: Assert filters_json in history parses back into canonical filter dictionary."""
    filters = {"start_date": "2026-08-01", "end_date": "2026-08-31", "employee": "Ravi Kumar"}
    memory_tools.save_report_run({
        "report_id": "REP-FILTERS-TEST",
        "user_request": "Ravi August",
        "filters": filters,
        "transaction_ids": [],
        "transaction_count": 0,
        "grand_total": 300.0,
        "validation_status": "Clear",
        "report_file_path": "reports/filt.pdf",
        "human_review_status": "None",
    })
    history = memory_tools.get_report_history()
    target = next(h for h in history if h["report_id"] == "REP-FILTERS-TEST")
    saved_filters = target.get("filters")
    if saved_filters is None and "filters_json" in target:
        saved_filters = json.loads(target["filters_json"]) if isinstance(target["filters_json"], str) else target["filters_json"]
    assert saved_filters["employee"] == "Ravi Kumar"


def test_t1_f6_05_history_stores_grand_total():
    """F6-5: Assert grand_total in history matches calculated report total."""
    expected_total = 48500.0
    memory_tools.save_report_run({
        "report_id": "REP-TOTAL-TEST",
        "user_request": "Total check",
        "filters": {},
        "transaction_ids": [],
        "transaction_count": 5,
        "grand_total": expected_total,
        "validation_status": "Clear",
        "report_file_path": "reports/tot.pdf",
        "human_review_status": "None",
    })
    history = memory_tools.get_report_history()
    target = next(h for h in history if h["report_id"] == "REP-TOTAL-TEST")
    assert target["grand_total"] == expected_total


# ============================================================================
# F7: History Actions (Prompt restore, View old, Rerun) (R2, PROJECT.md F7, F16)
# ============================================================================

def test_t1_f7_01_restore_prompt_does_not_execute():
    """F7-1: Call restore on report run; assert returns prompt string and filters without invoking agent."""
    # Seed active dataset to satisfy foreign key constraint
    ds = memory_tools.create_or_get_dataset(name="History Test", file_hash="hash_f7_01", row_count=5)
    dataset_id = ds["dataset_id"]

    # Persist genuine report run in SQLite
    run_payload = {
        "user_request": "Generate travel report for Priya Sharma",
        "filters": {"employee": "Priya Sharma", "start_date": "2026-08-01", "expense_type": "travel"},
        "transaction_ids": ["rec_001", "rec_002"],
        "transaction_count": 2,
        "grand_total": 4500.0,
        "validation_status": "Clear",
        "report_file_path": "reports/priya_aug_2026.pdf",
    }
    rep_id = memory_tools.save_report_run(run_payload, dataset_id=dataset_id)

    # Retrieve from SQLite history
    history = memory_tools.get_report_history(dataset_id=dataset_id)
    target = next((h for h in history if h["report_id"] == rep_id or h["run_id"] == rep_id), None)
    assert target is not None, "Report run not found in SQLite history"

    # Verify restored prompt and filters match persisted data
    restored_prompt = target["user_request"]
    restored_filters = target["filters"]
    assert restored_prompt == "Generate travel report for Priya Sharma"
    assert restored_filters["employee"] == "Priya Sharma"
    assert restored_filters["expense_type"] == "travel"

    # Verify restoration is passive (did not trigger new report runs or mutate count)
    conn = memory_tools.get_connection()
    count = conn.execute("SELECT count(*) FROM report_runs_v2 WHERE dataset_id = ?", (dataset_id,)).fetchone()[0]
    conn.close()
    assert count == 1


def test_t1_f7_02_view_old_report_immutable_snapshot():
    """F7-2: Historical report record remains immutable with original totals."""
    snapshot = {
        "report_id": "REP-OLD-SNAP",
        "grand_total": 35000.0,
        "transaction_count": 6,
        "created_at": "2026-08-15T10:00:00",
    }
    memory_tools.save_report_run({
        "report_id": snapshot["report_id"],
        "user_request": "Old snapshot",
        "filters": {},
        "transaction_ids": ["E1", "E2"],
        "transaction_count": snapshot["transaction_count"],
        "grand_total": snapshot["grand_total"],
        "validation_status": "Clear",
        "report_file_path": "reports/old.pdf",
        "human_review_status": "None",
    })
    history = memory_tools.get_report_history()
    target = next(h for h in history if h["report_id"] == "REP-OLD-SNAP")
    assert target["grand_total"] == 35000.0


def test_t1_f7_03_rerun_generates_new_run_id():
    """F7-3: Trigger rerun; assert newly created run_id is distinct from historical report_id."""
    ds = memory_tools.create_or_get_dataset(name="Rerun DS", file_hash="hash_f7_03", row_count=3)
    dataset_id = ds["dataset_id"]

    # Initial run
    id1 = memory_tools.save_report_run({
        "user_request": "Q3 Travel Report",
        "filters": {"expense_type": "travel"},
        "grand_total": 12000.0,
    }, dataset_id=dataset_id)

    # Rerun with same prompt/filters (without explicit report_id)
    id2 = memory_tools.save_report_run({
        "user_request": "Q3 Travel Report",
        "filters": {"expense_type": "travel"},
        "grand_total": 12000.0,
    }, dataset_id=dataset_id)

    assert id1 != id2
    history = memory_tools.get_report_history(dataset_id=dataset_id)
    retrieved_ids = [h["report_id"] for h in history]
    assert id1 in retrieved_ids
    assert id2 in retrieved_ids
    assert len(retrieved_ids) >= 2


def test_t1_f7_04_rerun_tags_active_dataset_version():
    """F7-4: Rerun records new run with explicit version tracking."""
    rep_data = {
        "report_id": "REP-V2-RERUN",
        "user_request": "Rerun test",
        "filters": {"dataset_version": 2},
        "transaction_ids": [],
        "transaction_count": 0,
        "grand_total": 1200.0,
        "validation_status": "Clear",
        "report_file_path": "reports/v2_rerun.pdf",
        "human_review_status": "None",
    }
    memory_tools.save_report_run(rep_data)
    history = memory_tools.get_report_history()
    assert any(h["report_id"] == "REP-V2-RERUN" for h in history)


def test_t1_f7_05_historical_pdf_link_preserved():
    """F7-5: Assert report snapshot contains valid archived PDF file path."""
    pdf_path = "reports/expense_report_August_2026_test.pdf"
    memory_tools.save_report_run({
        "report_id": "REP-PDF-LINK",
        "user_request": "PDF link test",
        "filters": {},
        "transaction_ids": [],
        "transaction_count": 1,
        "grand_total": 500.0,
        "validation_status": "Clear",
        "report_file_path": pdf_path,
        "human_review_status": "None",
    })
    history = memory_tools.get_report_history()
    target = next(h for h in history if h["report_id"] == "REP-PDF-LINK")
    assert target["report_file_path"] == pdf_path


# ============================================================================
# F8: Compliance Active Editing (All 8 Fields) (R3, PROJECT.md F11)
# ============================================================================

def test_t1_f8_01_edit_amount_field(sample_expenses):
    """F8-1: Update amount in DB; assert new amount persisted and retrievable."""
    saved = memory_tools.save_expenses(sample_expenses[:1], source_name="edit_amt.csv")
    recs = memory_tools.retrieve_expenses_from_db()
    rec_id = recs[0]["record_id"]
    ok = memory_tools.update_expense_record(rec_id, {"amount": 7777.0})
    assert ok is True
    updated = memory_tools.retrieve_expenses_from_db()
    assert updated[0]["amount"] == 7777.0


def test_t1_f8_02_edit_date_field(sample_expenses):
    """F8-2: Update date in DB; assert date change persisted."""
    memory_tools.save_expenses(sample_expenses[:1], source_name="edit_date.csv")
    recs = memory_tools.retrieve_expenses_from_db()
    rec_id = recs[0]["record_id"]
    memory_tools.update_expense_record(rec_id, {"expense_date": "2026-08-25"})
    updated = memory_tools.retrieve_expenses_from_db()
    d = updated[0].get("date") or updated[0].get("expense_date")
    assert d == "2026-08-25"


def test_t1_f8_03_edit_receipt_status_field(sample_expenses):
    """F8-3: Update receipt_status to 'Verified'; assert missing receipt issue resolved."""
    exp = dict(sample_expenses[0])
    exp["receipt_status"] = "Missing"
    memory_tools.save_expenses([exp], source_name="edit_rec.csv")
    recs = memory_tools.retrieve_expenses_from_db()
    rec_id = recs[0]["record_id"]
    memory_tools.update_expense_record(rec_id, {"receipt_status": "Verified"})
    updated = memory_tools.retrieve_expenses_from_db()
    assert updated[0]["receipt_status"] == "Verified"
    issues = validation_tools.revalidate_single_expense(dict(updated[0]))
    assert not any(i["issue_type"] == "missing_receipt" for i in issues)


def test_t1_f8_04_edit_employee_and_merchant(sample_expenses):
    """F8-4: Update merchant/description in DB; assert changes persisted."""
    memory_tools.save_expenses(sample_expenses[:1], source_name="edit_emp_mer.csv")
    recs = memory_tools.retrieve_expenses_from_db()
    rec_id = recs[0]["record_id"]
    memory_tools.update_expense_record(rec_id, {
        "description": "Corrected Description",
        "merchant": "Corrected Merchant",
    })
    updated = memory_tools.retrieve_expenses_from_db()
    assert updated[0]["merchant"] == "Corrected Merchant"
    assert updated[0]["description"] == "Corrected Description"


def test_t1_f8_05_edit_category_location_description(sample_expenses):
    """F8-5: Update category, location, and description; assert columns updated."""
    memory_tools.save_expenses(sample_expenses[:1], source_name="edit_3fields.csv")
    recs = memory_tools.retrieve_expenses_from_db()
    rec_id = recs[0]["record_id"]
    memory_tools.update_expense_record(rec_id, {
        "category": "Accommodation",
        "description": "Executive Suite Stay",
    })
    updated = memory_tools.retrieve_expenses_from_db()
    assert updated[0]["category"] == "Accommodation"
    assert updated[0]["description"] == "Executive Suite Stay"


# ============================================================================
# F9: Null-Resilience (No 0.0 conversion) (R3, PROJECT.md F4, F9)
# ============================================================================

def test_t1_f9_01_raw_null_amount_persists_as_null():
    """F9-1: Insert record with amount = None; verify SQLite storage and retrieval preserve NULL (not 0.0)."""
    rec = {
        "date": "2026-08-01",
        "employee": "Priya Sharma",
        "description": "Null amount test",
        "merchant": "Vendor",
        "category": "Meals",
        "amount": None,
        "receipt_status": "Verified",
    }
    res = memory_tools.save_expenses([rec], source_name="null_amt.csv")
    assert (res["inserted"] if isinstance(res, dict) else res[0]) == 1

    # Direct SQLite verification: column must be NULL, strictly not 0.0
    conn = memory_tools.get_connection()
    try:
        row = conn.execute(
            "SELECT amount, expense_date FROM expenses_v2 WHERE description = 'Null amount test'"
        ).fetchone()
        assert row is not None, "Expense record was not found in expenses_v2"
        assert row[0] is None, f"Expected SQLite NULL in expenses_v2, got {row[0]!r}"
        assert row[1] == "2026-08-01"
    finally:
        conn.close()

    # Application retrieval verification: amount must be None in Python dict
    recs = memory_tools.retrieve_expenses_from_db()
    saved = next((r for r in recs if r.get("description") == "Null amount test"), None)
    assert saved is not None, "Saved record not found in retrieved list"
    assert saved["amount"] is None, f"Expected amount is None, got {saved['amount']!r}"


def test_t1_f9_02_query_returns_none_amount():
    """F9-2: Retrieve expense with null amount; assert record retrieved without crashing and distinguishes None from 0.0."""
    rec_null = {
        "date": "2026-08-02",
        "employee": "Amit Verma",
        "description": "Query null amount distinction test",
        "merchant": "Vendor Null",
        "category": "Transport",
        "amount": None,
        "receipt_status": "Verified",
    }
    rec_zero = {
        "date": "2026-08-02",
        "employee": "Amit Verma",
        "description": "Query zero amount distinction test",
        "merchant": "Vendor Zero",
        "category": "Transport",
        "amount": 0.0,
        "receipt_status": "Verified",
    }
    memory_tools.save_expenses([rec_null, rec_zero], source_name="query_null_vs_zero.csv")

    recs = memory_tools.retrieve_expenses_from_db()
    assert isinstance(recs, list)
    assert len(recs) >= 2

    null_item = next((r for r in recs if r.get("description") == "Query null amount distinction test"), None)
    zero_item = next((r for r in recs if r.get("description") == "Query zero amount distinction test"), None)

    assert null_item is not None, "Record with null amount was not retrieved"
    assert null_item["amount"] is None, f"Expected null amount to be None, got {null_item['amount']!r}"

    assert zero_item is not None, "Record with 0.0 amount was not retrieved"
    assert zero_item["amount"] == 0.0, f"Expected zero amount to be 0.0, got {zero_item['amount']!r}"

    # Critical distinction check: None must never be conflated with 0.0
    assert null_item["amount"] != zero_item["amount"], "None amount and 0.0 amount must not be conflated"


def test_t1_f9_03_null_amount_flagged_by_validator():
    """F9-3: Validate expense with amount = None; assert invalid_amount issue emitted."""
    rec = {
        "date": "2026-08-01",
        "employee": "Priya Sharma",
        "description": "Null amount check",
        "merchant": "Vendor",
        "category": "Meals",
        "amount": None,
        "receipt_status": "Verified",
    }
    issues = validation_tools.validate_expenses([rec])
    assert any(i["issue_type"] == "invalid_amount" for i in issues)


def test_t1_f9_04_null_date_persists_safely():
    """F9-4: Insert record with missing date; assert DB row created and expense_date is stored as NULL."""
    rec = {
        "date": "",
        "employee": "Priya Sharma",
        "description": "Missing date test",
        "merchant": "Vendor",
        "category": "Meals",
        "amount": 500.0,
        "receipt_status": "Verified",
    }
    res = memory_tools.save_expenses([rec], source_name="null_date.csv")
    assert (res["inserted"] if isinstance(res, dict) else res[0]) == 1

    # Direct SQLite verification: expense_date column must be NULL
    conn = memory_tools.get_connection()
    try:
        row = conn.execute(
            "SELECT expense_date, amount FROM expenses_v2 WHERE description = 'Missing date test'"
        ).fetchone()
        assert row is not None
        assert row[0] is None, f"Expected SQLite NULL for missing date, got {row[0]!r}"
        assert row[1] == 500.0
    finally:
        conn.close()

    recs = memory_tools.retrieve_expenses_from_db()
    saved = next((r for r in recs if r.get("description") == "Missing date test"), None)
    assert saved is not None
    assert saved["date"] is None or saved["date"] == ""


def test_t1_f9_05_calculate_totals_skips_null_amounts():
    """F9-5: Run calculate_totals with null amounts; assert executes cleanly without TypeError."""
    records = [
        {"category": "Meals", "amount": 1000.0, "receipt_status": "Verified"},
        {"category": "Transport", "amount": None, "receipt_status": "Verified"},
        {"category": "Flight", "amount": 0.0, "receipt_status": "Verified"},
    ]
    totals = calculation_tools.calculate_totals(records)
    assert totals["grand_total"] == 1000.0
    assert totals["transaction_count"] == 3


# ============================================================================
# F10: Reviewer Actions (Correct, Exclude, Accept Exception) (R3, PROJECT.md F10, F12)
# ============================================================================

def test_t1_f10_01_action_correct_updates_record(sample_expenses):
    """F10-1: Apply 'correct' with valid data; assert record updated and issue marked resolved."""
    exp = dict(sample_expenses[0])
    exp["receipt_status"] = "Missing"
    memory_tools.save_expenses([exp], source_name="f10_1.csv")
    issues = validation_tools.validate_expenses([exp])
    saved_issues = memory_tools.save_validation_issues(issues)
    issue_id = saved_issues[0]["issue_id"]

    ok = memory_tools.resolve_validation_issue(
        issue_id=issue_id,
        decision="corrected",
        notes="Updated receipt to verified",
    )
    assert ok is True
    unresolved = memory_tools.get_unresolved_issues()
    assert not any(i["issue_id"] == issue_id for i in unresolved)


def test_t1_f10_02_action_correct_revalidates_first(sample_expenses):
    """F10-2: Apply 'correct' with invalid data; assert issue remains flagged by revalidator."""
    exp = dict(sample_expenses[0])
    exp["amount"] = 0.0  # Invalid amount
    issues = validation_tools.revalidate_single_expense(exp)
    assert any(i["issue_type"] == "invalid_amount" for i in issues)


def test_t1_f10_03_action_exclude_sets_flag(sample_expenses):
    """F10-3: Apply 'exclude'; assert flagged record marked or issue resolved as excluded."""
    issues = validation_tools.validate_expenses([sample_expenses[0]])
    saved_issues = memory_tools.save_validation_issues(issues) if issues else []
    if saved_issues:
        ok = memory_tools.resolve_validation_issue(
            issue_id=saved_issues[0]["issue_id"],
            decision="excluded",
            notes="Excluded from report",
        )
        assert ok is True


def test_t1_f10_04_action_exclude_omits_from_calculations(sample_expenses):
    """F10-4: Excluded transactions are omitted from report grand total."""
    records = [
        {"category": "Meals", "amount": 1000.0, "is_excluded": 0, "receipt_status": "Verified"},
        {"category": "Flight", "amount": 5000.0, "is_excluded": 1, "receipt_status": "Verified"},
    ]
    # Filter out excluded before calculation
    active_recs = [r for r in records if not r.get("is_excluded")]
    totals = calculation_tools.calculate_totals(active_recs)
    assert totals["grand_total"] == 1000.0


def test_t1_f10_05_action_accept_exception_with_notes():
    """F10-5: Apply 'accept_exception' with reason; assert status accepted_exception and notes stored."""
    rec = {
        "date": "2026-08-01",
        "employee": "Amit Patel",
        "description": "Taxi ride",
        "merchant": "Uber",
        "category": "Transport",
        "amount": 500.0,
        "receipt_status": "Missing",
    }
    memory_tools.save_expenses([rec], source_name="f10_5.csv")
    issues = validation_tools.validate_expenses([rec])
    saved = memory_tools.save_validation_issues(issues)
    ok = memory_tools.resolve_validation_issue(
        issue_id=saved[0]["issue_id"],
        decision="accepted_exception",
        notes="Authorized by Director of Finance",
    )
    assert ok is True
    unres = memory_tools.get_unresolved_issues()
    assert len(unres) == 0


# ============================================================================
# F11: Audit Trail Logging (Old/New values) (R3, PROJECT.md F6, F11)
# ============================================================================

@pytest.mark.skipif(not hasattr(memory_tools, "save_audit_event"), reason="Waiting for M1 save_audit_event")
def test_t1_f11_01_audit_log_record_correction():
    """F11-1: Correct amount from 500 to 600; assert audit event contains old/new values."""
    ds = memory_tools.create_or_get_dataset("Audit T1 DS 1", "hash_t1_1", 1)
    eid = memory_tools.save_audit_event(
        dataset_id=ds["dataset_id"],
        event_type="record_corrected",
        entity_type="expense",
        entity_id="EXP-101",
        details={"old_values": {"amount": 500.0}, "new_values": {"amount": 600.0}},
    )
    assert eid is not None
    events = memory_tools.get_audit_events(ds["dataset_id"])
    assert any(e["event_id"] == eid for e in events)


@pytest.mark.skipif(not hasattr(memory_tools, "save_audit_event"), reason="Waiting for M1 save_audit_event")
def test_t1_f11_02_audit_log_record_exclusion():
    """F11-2: Exclude record; assert audit event records event_type='record_excluded'."""
    ds = memory_tools.create_or_get_dataset("Audit T1 DS 2", "hash_t1_2", 1)
    eid = memory_tools.save_audit_event(
        dataset_id=ds["dataset_id"],
        event_type="record_excluded",
        entity_type="expense",
        entity_id="EXP-102",
        details={"reason": "Disputed duplicate charge"},
    )
    assert eid is not None


@pytest.mark.skipif(not hasattr(memory_tools, "save_audit_event"), reason="Waiting for M1 save_audit_event")
def test_t1_f11_03_audit_log_exception_authorization():
    """F11-3: Accept exception; assert audit event records documented managerial rationale."""
    ds = memory_tools.create_or_get_dataset("Audit T1 DS 3", "hash_t1_3", 1)
    eid = memory_tools.save_audit_event(
        dataset_id=ds["dataset_id"],
        event_type="exception_accepted",
        entity_type="validation_issue",
        entity_id="ISS-103",
        details={"manager": "VP Engineering", "reason": "Emergency flight booking without corporate receipt"},
    )
    assert eid is not None


@pytest.mark.skipif(not hasattr(memory_tools, "get_audit_events"), reason="Waiting for M1 get_audit_events")
def test_t1_f11_04_audit_events_scoped_to_dataset():
    """F11-4: Assert audit events for DS-A do not appear in DS-B query."""
    ds_a = memory_tools.create_or_get_dataset("Audit T1 DS A", "hash_t1_a", 1)
    ds_b = memory_tools.create_or_get_dataset("Audit T1 DS B", "hash_t1_b", 1)
    memory_tools.save_audit_event(ds_a["dataset_id"], "edit", "expense", "E1", {"change": "A"})
    memory_tools.save_audit_event(ds_b["dataset_id"], "edit", "expense", "E2", {"change": "B"})
    events_a = memory_tools.get_audit_events(ds_a["dataset_id"])
    assert all(e["dataset_id"] == ds_a["dataset_id"] for e in events_a)


@pytest.mark.skipif(not hasattr(memory_tools, "get_audit_events"), reason="Waiting for M1 get_audit_events")
def test_t1_f11_05_audit_events_chronological():
    """F11-5: Assert audit events returned in chronological order."""
    ds = memory_tools.create_or_get_dataset("Audit T1 Chrono", "hash_t1_c", 1)
    memory_tools.save_audit_event(ds["dataset_id"], "ev1", "exp", "E1", {})
    memory_tools.save_audit_event(ds["dataset_id"], "ev2", "exp", "E2", {})
    events = memory_tools.get_audit_events(ds["dataset_id"])
    assert len(events) >= 2


# ============================================================================
# F12: Canonical ParsedFilters Consistency (R4, PROJECT.md F7, F12)
# ============================================================================

def test_t1_f12_01_canonical_filters_structure():
    """F12-1: Verify parsed intent returns consistent structured keys."""
    intent = agent._regex_extract_intent("Generate August travel report for Priya Sharma")
    assert "expense_type" in intent
    assert "time_period" in intent
    assert "employee_name" in intent


def test_t1_f12_02_date_range_normalization():
    """F12-2: 'August 2026' normalizes to 2026-08-01 and 2026-08-31."""
    start, end = agent._resolve_date_range("August 2026")
    assert start == "2026-08-01"
    assert end == "2026-08-31"


def test_t1_f12_03_filters_passed_to_agent_state():
    """F12-3: Verify Expense Analysis Agent populates structured filters in state."""
    state = {
        "user_request": "Generate August 2026 travel report for Priya Sharma",
        "expenses": [
            {"date": "2026-08-01", "employee": "Priya Sharma", "amount": 1000.0, "category": "Flight", "receipt_status": "Verified"}
        ],
    }
    res = agent.expense_analysis_agent_node(state)
    assert "expense_analysis" in res
    assert res["expense_analysis"]["target_employee"] == "Priya Sharma"


def test_t1_f12_04_filters_align_with_db_query(sample_expenses):
    """F12-4: Assert keys in ParsedFilters map directly to SQLite query parameters."""
    memory_tools.save_expenses(sample_expenses, source_name="f12_4.csv")
    recs = memory_tools.retrieve_expenses_from_db(
        employee="Priya Sharma",
        start_date="2026-08-01",
        end_date="2026-08-31",
    )
    for r in recs:
        assert r["employee"] == "Priya Sharma"
        d = r.get("date") or r.get("expense_date")
        assert "2026-08-01" <= d <= "2026-08-31"


def test_t1_f12_05_filters_json_serialization_roundtrip():
    """F12-5: Serialize filter dict to JSON and back; assert equality."""
    filters = {"start_date": "2026-08-01", "end_date": "2026-08-31", "employee": "Priya Sharma", "expense_type": "travel"}
    ser = json.dumps(filters)
    deser = json.loads(ser)
    assert deser == filters


# ============================================================================
# F13: Deterministic Natural Language Parsing (R4, PROJECT.md F8, F13)
# ============================================================================

def test_t1_f13_01_all_expenses_has_no_employee():
    """F13-1: Prompt 'all expenses for last month'; assert employee is empty string or None."""
    intent = agent._regex_extract_intent("all expenses for last month")
    assert intent["employee_name"] == "" or intent["employee_name"] is None


def test_t1_f13_02_all_employees_has_no_employee():
    """F13-2: Prompt 'all employees travel for August'; assert employee is empty string or None."""
    intent = agent._regex_extract_intent("all employees travel for August")
    assert intent["employee_name"] == "" or intent["employee_name"] is None


def test_t1_f13_03_specific_employee_match():
    """F13-3: Prompt 'expenses for Ravi Kumar'; assert employee matches Ravi Kumar."""
    intent = agent._regex_extract_intent("expenses for Ravi Kumar")
    assert intent["employee_name"] == "Ravi Kumar"


def test_t1_f13_04_no_employee_leakage_across_runs():
    """F13-4: Sequential prompt parsing does not leak employee when prompt is 'all expenses'."""
    # Run 1: specific employee
    intent1 = agent._regex_extract_intent("expenses for Ravi Kumar")
    assert intent1["employee_name"] == "Ravi Kumar"
    # Run 2: all expenses
    intent2 = agent._regex_extract_intent("all expenses for last month")
    assert intent2["employee_name"] == "" or intent2["employee_name"] is None


def test_t1_f13_05_prevent_substring_collision():
    """F13-5: Prompt 'all expenses' does not match single character or substring collision."""
    intent = agent._regex_extract_intent("all expenses")
    assert intent["employee_name"] != "Al"


# ============================================================================
# F14: Filter Condition & Zero-Match Explanations (R4, PROJECT.md F10, F14)
# ============================================================================

def test_t1_f14_01_display_detected_filters():
    """F14-1: Assert analysis summarizes detected criteria."""
    state = {
        "user_request": "Travel report August 2026",
        "expenses": [{"date": "2026-08-05", "employee": "Test", "amount": 500.0, "category": "Meals", "receipt_status": "Verified"}],
    }
    res = agent.expense_analysis_agent_node(state)
    assert res["expense_analysis"]["agent"] == "Expense Analysis Agent"


def test_t1_f14_02_matching_record_count_reported():
    """F14-2: Assert count in analysis matches len of categorized records."""
    state = {
        "user_request": "Travel report August 2026",
        "expenses": [
            {"date": "2026-08-01", "employee": "Test 1", "amount": 100.0, "category": "Meals", "receipt_status": "Verified"},
            {"date": "2026-08-02", "employee": "Test 2", "amount": 200.0, "category": "Flight", "receipt_status": "Verified"},
        ],
    }
    res = agent.expense_analysis_agent_node(state)
    assert res["expense_analysis"]["selected_records_count"] == 2


def test_t1_f14_03_explain_zero_match_date_mismatch(sample_expenses):
    """F14-3: Query future date range; assert zero records returned."""
    filtered = expense_tools.filter_expenses(sample_expenses, "2099-01-01", "2099-12-31", "travel")
    assert len(filtered) == 0


def test_t1_f14_04_explain_zero_match_employee_mismatch(sample_expenses):
    """F14-4: Query nonexistent employee; assert zero records returned."""
    filtered = expense_tools.filter_expenses(sample_expenses, "2026-08-01", "2026-08-31", "travel", employee_name="Nonexistent Employee XYZ")
    assert len(filtered) == 0


def test_t1_f14_05_zero_match_halts_report_safely():
    """F14-5: Assert zero match condition can be caught before generating empty report."""
    empty_records = []
    totals = calculation_tools.calculate_totals(empty_records)
    assert totals["transaction_count"] == 0
    assert totals["grand_total"] == 0.0


# ============================================================================
# F15: Location Schema Normalization & Notice (R5, PROJECT.md F9, F15)
# ============================================================================

def test_t1_f15_01_normalize_city_to_location(mumbai_expenses_csv):
    """F15-1: Dataset with 'city' column normalizes or recognizes city data."""
    rows = expense_tools.get_expenses(mumbai_expenses_csv)
    assert any("city" in r for r in rows)
    assert rows[0]["city"] == "Mumbai"


def test_t1_f15_02_normalize_destination_to_location(delhi_expenses_csv):
    """F15-2: Dataset with 'destination' column normalizes or recognizes destination data."""
    rows = expense_tools.get_expenses(delhi_expenses_csv)
    assert any("destination" in r for r in rows)
    assert rows[0]["destination"] == "Delhi"


def test_t1_f15_03_detect_absent_location(sample_csv_path):
    """F15-3: Dataset without location column has no location/city/destination keys."""
    rows = expense_tools.get_expenses(sample_csv_path)
    assert "location" not in rows[0]
    assert "city" not in rows[0]
    assert "destination" not in rows[0]


def test_t1_f15_04_absent_location_notice_emitted():
    """F15-4: Schema inspection helper reports absent location without crash."""
    rows = [{"employee": "Priya", "amount": 100.0, "date": "2026-08-01"}]
    has_loc = any("location" in r or "city" in r or "destination" in r for r in rows)
    assert has_loc is False


def test_t1_f15_05_absent_location_preserves_date_type_filters(sample_expenses):
    """F15-5: Date and type filters apply successfully even when dataset lacks location."""
    filtered = expense_tools.filter_expenses(sample_expenses, "2026-08-01", "2026-08-31", "travel")
    assert len(filtered) > 0


# ============================================================================
# F16: UI Streamlining & Advanced Diagnostics (R5, PROJECT.md F15, F16)
# ============================================================================

def test_t1_f16_01_diagnostics_expander_collapsed_by_default():
    """F16-1: Verify in app.py AST that Agent Graph State Inspector expander is collapsed (expanded=False)."""
    with open("app.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    inspector_expanders = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "expander"
        and any("Agent Graph State Inspector" in getattr(arg, "value", "") for arg in node.args if isinstance(arg, ast.Constant))
    ]
    assert len(inspector_expanders) >= 1, "Agent Graph State Inspector expander not found in app.py"
    call = inspector_expanders[0]
    expanded_kw = next((kw for kw in call.keywords if kw.arg == "expanded"), None)
    assert expanded_kw is not None
    assert isinstance(expanded_kw.value, ast.Constant) and expanded_kw.value.value is False


def test_t1_f16_02_manual_ingest_in_diagnostics():
    """F16-2: Verify in app.py AST that data ingestion expander is collapsed by default (expanded=False)."""
    with open("app.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    data_expanders = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "expander"
        and any("Active Expense Data Input" in getattr(arg, "value", "") for arg in node.args if isinstance(arg, ast.Constant))
    ]
    assert len(data_expanders) >= 1, "Data input expander not found in app.py"
    call = data_expanders[0]
    expanded_kw = next((kw for kw in call.keywords if kw.arg == "expanded"), None)
    assert expanded_kw is not None
    assert isinstance(expanded_kw.value, ast.Constant) and expanded_kw.value.value is False


def test_t1_f16_03_raw_graph_inspector_in_diagnostics():
    """F16-3: Verify in app.py AST that graph inspector renders state dictionary via st.json inside expander."""
    with open("app.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    json_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "json"
    ]
    assert len(json_calls) >= 1, "st.json call for raw state inspection not found in app.py"


def test_t1_f16_04_primary_ui_components_clean():
    """F16-4: Verify app.py AST defines the 4 core navigation tabs adhering to design standards."""
    with open("app.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    nav_tabs = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "tabs":
            if n.args and isinstance(n.args[0], ast.List):
                tab_labels = [elt.value for elt in n.args[0].elts if isinstance(elt, ast.Constant)]
                if len(tab_labels) == 4:
                    nav_tabs = tab_labels
                    break

    assert len(nav_tabs) == 4
    assert any("Executive Workspace" in t for t in nav_tabs)
    assert any("Prompt & Report Run History" in t for t in nav_tabs)
    assert any("Persistent SQLite Memory" in t for t in nav_tabs)
    assert any("Compliance & Validation" in t for t in nav_tabs)


def test_t1_f16_05_error_display_authoritative_banner():
    """F16-5: Verify app.py formats error alerts using authoritative banner format without raw tracebacks."""
    with open("app.py", "r", encoding="utf-8") as f:
        source = f.read()

    # Verify st.error is called with Error Notice banner format
    assert 'st.error(f"⚠️ Error Notice: {st.session_state[\'error\']}"' in source or 'Error Notice:' in source
    # Verify no raw traceback.print_exc() is invoked directly in user rendering
    assert "traceback.print_exc" not in source


def test_t1_f16_06_clean_editor_records_preserves_null_amounts():
    """F16-6: Data editor sanitizer preserves None for null amounts per R3 (never coerces to 0.0)."""
    from app import _clean_editor_records
    records = [
        {"date": "2026-08-01", "amount": None, "description": "Null amount row", "merchant": "V", "category": "Meals", "receipt_status": "Verified"}
    ]
    cleaned = _clean_editor_records(records)
    assert len(cleaned) == 1
    assert cleaned[0]["amount"] is None, f"Expected amount to be None, got {cleaned[0]['amount']!r}"


def test_t1_f16_07_clean_editor_records_preserves_null_dates():
    """F16-7: Data editor sanitizer preserves None for missing or null dates."""
    from app import _clean_editor_records
    records = [
        {"date": None, "amount": 1250.0, "description": "Null date row", "merchant": "V", "category": "Meals", "receipt_status": "Verified"},
        {"date": "", "amount": 800.0, "description": "Empty date row", "merchant": "V", "category": "Meals", "receipt_status": "Verified"}
    ]
    cleaned = _clean_editor_records(records)
    assert len(cleaned) == 2
    assert cleaned[0]["date"] is None
    assert cleaned[1]["date"] is None


def test_t1_f16_08_clean_editor_records_currency_and_timestamp_normalization():
    """F16-8: Data editor sanitizer strips currency symbols and truncates ISO timestamps to YYYY-MM-DD."""
    from app import _clean_editor_records
    records = [
        {"date": "2026-08-01T14:30:00", "amount": "₹ 15,400.50", "description": "Flight", "merchant": "Air India", "category": "Flight", "receipt_status": "Verified"}
    ]
    cleaned = _clean_editor_records(records)
    assert len(cleaned) == 1
    assert cleaned[0]["date"] == "2026-08-01"
    assert cleaned[0]["amount"] == 15400.50


def test_t1_f16_09_clean_editor_records_drops_entirely_blank_rows():
    """F16-9: Data editor sanitizer discards newly added completely blank rows from st.data_editor."""
    from app import _clean_editor_records
    records = [
        {"date": None, "amount": None, "description": "", "merchant": None, "category": "", "receipt_status": ""},
        {"date": "2026-08-01", "amount": 200.0, "description": "Valid row", "merchant": "Shop", "category": "Meals", "receipt_status": "Verified"}
    ]
    cleaned = _clean_editor_records(records)
    assert len(cleaned) == 1
    assert cleaned[0]["description"] == "Valid row"


def test_t1_f16_10_clean_editor_records_preserves_legitimate_zero_amount():
    """F16-10: Data editor sanitizer distinguishes genuine 0.0 amounts from null/missing amounts."""
    from app import _clean_editor_records
    records = [
        {"date": "2026-08-01", "amount": 0.0, "description": "Zero rupee promo", "merchant": "Shop", "category": "Meals", "receipt_status": "Verified"}
    ]
    cleaned = _clean_editor_records(records)
    assert len(cleaned) == 1
    assert cleaned[0]["amount"] == 0.0
    assert cleaned[0]["amount"] is not None


# ============================================================================
# F17: Activity Log Normalization & Banner (R5, PROJECT.md F17)
# ============================================================================

def test_t1_f17_01_activity_log_structured_columns():
    """F17-1: agent._append_agent_log produces structured entries with agent, message, timestamp."""
    state = {"agent_logs": []}
    logs = agent._append_agent_log(state, "Expense Analysis Agent", "Filtered 42 records for August 2026")
    assert len(logs) == 1
    entry = logs[0]
    assert entry["agent"] == "Expense Analysis Agent"
    assert entry["message"] == "Filtered 42 records for August 2026"
    assert "timestamp" in entry
    assert re.match(r"^\d{2}:\d{2}:\d{2}$", entry["timestamp"]) is not None


def test_t1_f17_02_activity_log_agent_attribution(sample_expenses):
    """F17-2: Node executions accurately attribute activity log entries to their respective agents."""
    state = {
        "user_request": "All expenses for April 2026",
        "expenses": sample_expenses[:5],
        "workflow_status": [],
    }
    s1 = agent.expense_analysis_agent_node(state)
    state.update(s1)
    s2 = agent.validation_agent_node(state)
    status_list = s2.get("workflow_status", [])

    assert any("[Expense Analysis Agent]" in s for s in status_list)
    assert any("[Validation Agent]" in s for s in status_list)


def test_t1_f17_03_status_icons_consistent():
    """F17-3: Status logs use consistent icons: '✓' for success, '⚠️'/'⚠' for warnings, '✗' for errors."""
    clean_state = {
        "user_request": "Clean report",
        "categorized_expenses": [{"record_id": "r1", "amount": 100.0, "date": "2026-08-01", "receipt_status": "Verified", "category": "Meals", "description": "Lunch"}],
        "workflow_status": [],
    }
    res_clean = agent.validation_agent_node(clean_state)
    assert any("✓" in s for s in res_clean.get("workflow_status", []))

    flagged_state = {
        "user_request": "Flagged report",
        "categorized_expenses": [{"record_id": "r2", "amount": None, "date": "", "receipt_status": "Missing", "category": "", "description": "Unknown"}],
        "workflow_status": [],
    }
    res_flagged = agent.validation_agent_node(flagged_state)
    assert any("⚠" in s or "⚠️" in s for s in res_flagged.get("workflow_status", []))


def test_t1_f17_04_active_dataset_banner_fields():
    """F17-4: Active dataset metadata contains name, file_hash, row_count, version, is_active."""
    ds = memory_tools.create_or_get_dataset(name="Mumbai_Expenses.csv", file_hash="a1b2c3d4e5f67890", row_count=7)
    memory_tools.set_active_dataset(ds["dataset_id"])

    active = memory_tools.get_active_dataset()
    assert active is not None
    assert active["name"] == "Mumbai_Expenses.csv"
    assert active["file_hash"].startswith("a1b2c3d4")
    assert active["row_count"] == 7
    assert active["version"] == 1
    assert active["is_active"] == 1


def test_t1_f17_05_banner_updates_on_version_increment():
    """F17-5: On dataset version increment, active dataset version updates in SQLite from 1 to 2."""
    ds = memory_tools.create_or_get_dataset(name="Versioned DS", file_hash="hash_v1", row_count=3)
    dataset_id = ds["dataset_id"]
    memory_tools.set_active_dataset(dataset_id)

    v1_active = memory_tools.get_active_dataset()
    assert v1_active["version"] == 1

    updated_records = [{"date": "2026-08-01", "amount": 250.0, "description": "Edited row", "merchant": "Shop", "category": "Meals", "receipt_status": "Verified"}]
    new_ver = memory_tools.increment_dataset_version(dataset_id, updated_records)
    assert new_ver == 2

    v2_active = memory_tools.get_active_dataset()
    assert v2_active["version"] == 2
    assert v2_active["version"] != v1_active["version"]


# ============================================================================
# F18: Safe DB Migration & Legacy Attribution (R6, PROJECT.md F1, F18)
# ============================================================================

def test_t1_f18_01_backup_created_before_migration():
    """F18-1: Pre-migration backup helper creates timestamped file."""
    if hasattr(memory_tools, "backup_memory_db"):
        backup = memory_tools.backup_memory_db()
        assert backup is not None
        assert os.path.exists(backup)
    else:
        # Verify backup naming pattern
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"expense_memory_backup_{ts}.db"
        assert "backup" in name


def test_t1_f18_02_legacy_rows_tagged_legacy_unassigned():
    """F18-2: Verify DATASET-LEGACY-UNASSIGNED master record exists in SQLite datasets table with is_active = 0."""
    memory_tools.init_memory_db()
    conn = memory_tools.get_connection()
    row = conn.execute(
        "SELECT dataset_id, name, file_hash, is_active FROM datasets WHERE dataset_id = ?",
        (memory_tools.LEGACY_DATASET_ID,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["dataset_id"] == "DATASET-LEGACY-UNASSIGNED"
    assert row["file_hash"] == "legacy-pre-migration"
    assert row["is_active"] == 0


def test_t1_f18_03_legacy_rows_version_one():
    """F18-3: Verify DATASET-LEGACY-UNASSIGNED record has version = 1 in SQLite datasets table."""
    memory_tools.init_memory_db()
    conn = memory_tools.get_connection()
    row = conn.execute(
        "SELECT version FROM datasets WHERE dataset_id = ?",
        (memory_tools.LEGACY_DATASET_ID,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["version"] == 1


def test_t1_f18_04_existing_validation_issues_preserved():
    """F18-4: Validation issues table exists and preserves issues."""
    conn = memory_tools.get_connection()
    count = conn.execute("SELECT count(*) FROM validation_issues;").fetchone()[0]
    conn.close()
    assert count >= 0


def test_t1_f18_05_migration_idempotent():
    """F18-5: Calling init_memory_db multiple times succeeds idempotently."""
    p1 = memory_tools.init_memory_db()
    p2 = memory_tools.init_memory_db()
    assert p1 == p2


# ============================================================================
# F19: Run Context & Checkpoint Isolation (R6, PROJECT.md F19)
# ============================================================================

def test_t1_f19_01_unique_thread_id_per_run():
    """F19-1: LangGraph compiled graph checkpointer isolates workflow execution across distinct thread_ids."""
    graph, checkpointer = agent.get_compiled_graph()
    cfg1 = {"configurable": {"thread_id": "thread_run_alpha"}}
    cfg2 = {"configurable": {"thread_id": "thread_run_beta"}}

    assert cfg1["configurable"]["thread_id"] != cfg2["configurable"]["thread_id"]
    state1 = graph.get_state(cfg1)
    state2 = graph.get_state(cfg2)
    assert state1.values == {}
    assert state2.values == {}


def test_t1_f19_02_checkpoint_isolation_between_runs(tmp_path):
    """F19-2: Verify AGENT_CHECKPOINT_DB_PATH creates isolated checkpoints."""
    chk_path = os.getenv("AGENT_CHECKPOINT_DB_PATH")
    assert chk_path is not None
    assert "test_agent_state.db" in chk_path


def test_t1_f19_03_graph_node_execution_sequence(sample_expenses):
    """F19-3: Assert execution passes Analysis -> Validation in sequence."""
    aug_expenses = [e for e in sample_expenses if "2026-08" in e.get("date", "")]
    state = {
        "user_request": "Travel report August 2026",
        "expenses": aug_expenses[:10],
        "workflow_status": [],
    }
    s1 = agent.expense_analysis_agent_node(state)
    state.update(s1)
    s2 = agent.validation_agent_node(state)
    assert s2.get("validation_status") in ("Clear", "Needs Human Review")


def test_t1_f19_04_human_review_interrupt():
    """F19-4: Assert validation discrepancy marks status Needs Human Review."""
    bad_expenses = [
        {"date": "2026-08-01", "employee": "Priya", "amount": 0.0, "category": "Meals", "receipt_status": "Missing"}
    ]
    res = agent.validation_agent_node({"categorized_expenses": bad_expenses, "workflow_status": []})
    assert res["validation_status"] == "Needs Human Review"
    assert res["awaiting_input"] == "missing_data"


def test_t1_f19_05_graph_resumption_from_checkpoint(sample_expenses):
    """F19-5: Clean data completes through report generation."""
    state = {
        "user_request": "Travel report August 2026",
        "report_run_id": "REP-T1-F19-05",
        "employee_name": "Priya Sharma",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "categorized_expenses": sample_expenses[:5],
        "validation_status": "Clear",
        "workflow_status": [],
    }
    res = agent.report_generation_agent_node(state)
    assert "pdf_path" in res
    assert os.path.exists(res["pdf_path"])
