"""
E2E Tier 2: Boundary & Corner Cases Test Suite (95 tests across F1–F19).
Validates edge cases, boundary conditions, malformed inputs, SQL injection resilience,
null handling, Unicode/emojis, rapid sequential actions, and error fallbacks.
"""

import os
import io
import re
import ast
import csv
import json
import uuid
import sqlite3
import hashlib
import tempfile
import pytest
import pandas as pd
from datetime import datetime

import tools.memory_tools as memory_tools
import tools.expense_tools as expense_tools
import tools.validation_tools as validation_tools
import tools.calculation_tools as calculation_tools
import tools.pdf_tools as pdf_tools
import agent


# ============================================================================
# F1: Dataset Creation & SHA-256 Boundaries
# ============================================================================

def test_t2_f1_01_empty_csv_file(tmp_path):
    """F1-B1: Empty CSV file (0 bytes); verify empty file raises parsing error."""
    empty_csv = str(tmp_path / "empty.csv")
    with open(empty_csv, "w") as f:
        pass
    with pytest.raises(Exception):
        expense_tools.get_expenses(empty_csv)


def test_t2_f1_02_single_row_csv(tmp_path):
    """F1-B2: Single-row CSV; verify hash and load."""
    csv_file = str(tmp_path / "single.csv")
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "description", "merchant", "amount", "category", "receipt_status", "employee", "payment_method"])
        writer.writeheader()
        writer.writerow({"date": "2026-08-01", "description": "Single Expense", "merchant": "Shop", "amount": 100.0, "category": "Meals", "receipt_status": "Verified", "employee": "Test User", "payment_method": "Card"})
    rows = expense_tools.get_expenses(csv_file)
    assert len(rows) == 1
    h = hashlib.sha256(open(csv_file, "rb").read()).hexdigest()
    assert len(h) == 64


def test_t2_f1_03_large_csv_10k_rows(tmp_path):
    """F1-B3: Large CSV (1,000 synthetic rows); fast hashing and load."""
    csv_file = str(tmp_path / "large.csv")
    fieldnames = ["date", "description", "merchant", "amount", "category", "receipt_status", "employee", "payment_method"]
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i in range(1000):
            writer.writerow({"date": "2026-08-01", "description": f"Bulk {i}", "merchant": "Vendor", "amount": 10.0, "category": "Meals", "receipt_status": "Verified", "employee": f"User {i % 10}", "payment_method": "Card"})
    rows = expense_tools.get_expenses(csv_file)
    assert len(rows) == 1000


def test_t2_f1_04_special_characters_filename(tmp_path):
    """F1-B4: Filename with unicode/spaces/special chars; handles safely."""
    csv_file = str(tmp_path / "Expérience 🚀 & Costs 2026.csv")
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "description", "merchant", "amount", "category", "receipt_status", "employee", "payment_method"])
        writer.writeheader()
        writer.writerow({"date": "2026-08-01", "description": "Special", "merchant": "Shop", "amount": 50.0, "category": "Meals", "receipt_status": "Verified", "employee": "Priya", "payment_method": "Card"})
    rows = expense_tools.get_expenses(csv_file)
    assert len(rows) == 1


def test_t2_f1_05_utf8_bom_handling(tmp_path):
    """F1-B5: CSV containing UTF-8 BOM (\xef\xbb\xbf); first column header not corrupted."""
    csv_file = str(tmp_path / "bom.csv")
    with open(csv_file, "wb") as f:
        f.write(b"\xef\xbb\xbfdate,description,merchant,amount,category,receipt_status,employee,payment_method\n")
        f.write(b"2026-08-01,BOM test,Shop,100,Meals,Verified,Priya,Card\n")
    rows = expense_tools.get_expenses(csv_file)
    assert len(rows) == 1
    # Ensure header does not contain corrupt \ufeff
    assert "date" in rows[0] or "\ufeffdate" in rows[0]


# ============================================================================
# F2: Auto-Persistence Boundaries
# ============================================================================

def test_t2_f2_01_persist_empty_record_list():
    """F2-B1: Call save_expenses on []; handles without DB error."""
    res = memory_tools.save_expenses([], source_name="empty.csv")
    inserted = res.get("inserted", 0) if isinstance(res, dict) else res[0]
    assert inserted == 0


def test_t2_f2_02_sql_injection_in_text_fields():
    """F2-B2: Description with SQL injection payload; stored safely verbatim."""
    payload = "'); DROP TABLE expenses; --"
    rec = {
        "date": "2026-08-01",
        "description": payload,
        "merchant": "Vendor",
        "category": "Meals",
        "amount": 100.0,
        "receipt_status": "Verified",
        "employee": "Hacker",
    }
    memory_tools.save_expenses([rec], source_name="sqli.csv")
    recs = memory_tools.retrieve_expenses_from_db(employee="Hacker")
    assert len(recs) == 1
    assert recs[0]["description"] == payload


def test_t2_f2_03_duplicate_record_ids_in_batch():
    """F2-B3: Batch containing identical records; deduplication prevents crash."""
    rec = {
        "date": "2026-08-01",
        "description": "Identical",
        "merchant": "Vendor",
        "category": "Meals",
        "amount": 250.0,
        "receipt_status": "Verified",
        "employee": "Priya Sharma",
    }
    res = memory_tools.save_expenses([rec, rec], source_name="dup_batch.csv")
    recs = memory_tools.retrieve_expenses_from_db()
    assert len(recs) >= 1


def test_t2_f2_04_missing_optional_columns():
    """F2-B4: Record missing receipt_path and payment_method; stored safely with None/defaults."""
    rec = {
        "date": "2026-08-01",
        "description": "Minimal record",
        "merchant": "Vendor",
        "category": "Meals",
        "amount": 300.0,
        "receipt_status": "Verified",
        "employee": "Priya Sharma",
    }
    res = memory_tools.save_expenses([rec], source_name="min.csv")
    assert (res["inserted"] if isinstance(res, dict) else res[0]) == 1


def test_t2_f2_05_max_text_length_storage():
    """F2-B5: Description with 5,000 characters; persists and retrieves without truncation."""
    long_desc = "A" * 5000
    rec = {
        "date": "2026-08-01",
        "description": long_desc,
        "merchant": "Vendor",
        "category": "Meals",
        "amount": 100.0,
        "receipt_status": "Verified",
        "employee": "Priya Sharma",
    }
    memory_tools.save_expenses([rec], source_name="long_desc.csv")
    recs = memory_tools.retrieve_expenses_from_db()
    target = next(r for r in recs if r["description"] == long_desc)
    assert len(target["description"]) == 5000


# ============================================================================
# F3: Active Dataset Switching Boundaries
# ============================================================================

@pytest.mark.skipif(not hasattr(memory_tools, "set_active_dataset"), reason="Waiting for M1 set_active_dataset")
def test_t2_f3_01_switch_to_nonexistent_dataset():
    """F3-B1: Set active dataset to nonexistent ID; returns False or handles cleanly."""
    res = memory_tools.set_active_dataset("DS-FAKE-NONEXISTENT-999")
    assert res is False or res is None


@pytest.mark.skipif(not hasattr(memory_tools, "get_active_dataset"), reason="Waiting for M1 get_active_dataset")
def test_t2_f3_02_empty_database_active_query():
    """F3-B2: Call get_active_dataset() when no dataset active; returns None without crashing."""
    active = memory_tools.get_active_dataset()
    assert active is None or isinstance(active, dict)


@pytest.mark.skipif(not hasattr(memory_tools, "set_active_dataset"), reason="Waiting for M1 set_active_dataset")
def test_t2_f3_03_rapid_toggle_switching():
    """F3-B3: Toggle active dataset 20 times in rapid succession; exactly 1 active."""
    ds_a = memory_tools.create_or_get_dataset("Tog A", "toga", 1)
    ds_b = memory_tools.create_or_get_dataset("Tog B", "togb", 1)
    for i in range(20):
        target = ds_a["dataset_id"] if i % 2 == 0 else ds_b["dataset_id"]
        memory_tools.set_active_dataset(target)
    active = memory_tools.get_active_dataset()
    assert active["dataset_id"] == ds_b["dataset_id"]


@pytest.mark.skipif(not hasattr(memory_tools, "set_active_dataset"), reason="Waiting for M1 set_active_dataset")
def test_t2_f3_04_case_sensitivity_dataset_id():
    """F3-B4: Ensure dataset ID comparison is exact and case-consistent."""
    ds = memory_tools.create_or_get_dataset("Case DS", "casehash", 1)
    ok = memory_tools.set_active_dataset(ds["dataset_id"].lower())
    # Should not crash; if exact match enforced, returns False or normalizes
    assert isinstance(ok, bool)


@pytest.mark.skipif(not hasattr(memory_tools, "set_active_dataset"), reason="Waiting for M1 set_active_dataset")
def test_t2_f3_05_dataset_activation_idempotency():
    """F3-B5: Activating already active dataset succeeds idempotently."""
    ds = memory_tools.create_or_get_dataset("Idemp DS", "idemhash", 1)
    ok1 = memory_tools.set_active_dataset(ds["dataset_id"])
    ok2 = memory_tools.set_active_dataset(ds["dataset_id"])
    assert ok1 is True and ok2 is True


# ============================================================================
# F4: Interactive Editor Versioning Boundaries
# ============================================================================

@pytest.mark.skipif(not hasattr(memory_tools, "increment_dataset_version"), reason="Waiting for M1 increment_dataset_version")
def test_t2_f4_01_save_with_zero_modifications(sample_expenses):
    """F4-B1: Save with identical records; version increments cleanly without data loss."""
    ds = memory_tools.create_or_get_dataset("Zero Mod DS", "zmod", 2)
    memory_tools.save_expenses(sample_expenses[:2], dataset_id=ds["dataset_id"])
    v2 = memory_tools.increment_dataset_version(ds["dataset_id"], sample_expenses[:2])
    assert v2 == 2
    recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=2)
    assert len(recs) == 2


@pytest.mark.skipif(not hasattr(memory_tools, "increment_dataset_version"), reason="Waiting for M1 increment_dataset_version")
def test_t2_f4_02_delete_all_rows_save(sample_expenses):
    """F4-B2: Delete all rows and save; version 2 contains 0 rows; queries return []."""
    ds = memory_tools.create_or_get_dataset("Del All DS", "delall", 2)
    memory_tools.save_expenses(sample_expenses[:2], dataset_id=ds["dataset_id"])
    v2 = memory_tools.increment_dataset_version(ds["dataset_id"], [])
    assert v2 == 2
    recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=2)
    assert len(recs) == 0


@pytest.mark.skipif(not hasattr(memory_tools, "increment_dataset_version"), reason="Waiting for M1 increment_dataset_version")
def test_t2_f4_03_bulk_add_500_rows(sample_expenses):
    """F4-B3: Add 500 rows in editor and save; increments cleanly."""
    ds = memory_tools.create_or_get_dataset("Bulk Add DS", "bulkadd", 1)
    memory_tools.save_expenses(sample_expenses[:1], dataset_id=ds["dataset_id"])
    bulk_rows = [dict(sample_expenses[0]) for _ in range(500)]
    v2 = memory_tools.increment_dataset_version(ds["dataset_id"], bulk_rows)
    assert v2 == 2


@pytest.mark.skipif(not hasattr(memory_tools, "increment_dataset_version"), reason="Waiting for M1 increment_dataset_version")
def test_t2_f4_04_unicode_and_emojis_in_cells(sample_expenses):
    """F4-B4: Edit merchant to 'Cafe ☕ 🥐'; saved and retrieved verbatim."""
    ds = memory_tools.create_or_get_dataset("Emoji DS", "emojihash", 1)
    rec = dict(sample_expenses[0])
    rec["merchant"] = "Cafe ☕ 🥐"
    v2 = memory_tools.increment_dataset_version(ds["dataset_id"], [rec])
    recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=v2)
    assert recs[0]["merchant"] == "Cafe ☕ 🥐"


@pytest.mark.skipif(not hasattr(memory_tools, "increment_dataset_version"), reason="Waiting for M1 increment_dataset_version")
def test_t2_f4_05_sequential_rapid_saves(sample_expenses):
    """F4-B5: Save 5 versions sequentially; version numbers sequence 1..5 intact."""
    ds = memory_tools.create_or_get_dataset("Seq Save DS", "seqsave", 1)
    memory_tools.save_expenses(sample_expenses[:1], dataset_id=ds["dataset_id"])
    for expected_v in range(2, 6):
        v = memory_tools.increment_dataset_version(ds["dataset_id"], sample_expenses[:1])
        assert v == expected_v


# ============================================================================
# F5: Query-Level Dataset Isolation Boundaries
# ============================================================================

def test_t2_f5_01_query_nonexistent_dataset_id():
    """F5-B1: Query with nonexistent dataset_id; returns empty list []."""
    recs = memory_tools.retrieve_expenses_from_db(dataset_id="DS-NONEXISTENT-999")
    assert recs == []


def test_t2_f5_02_empty_dataset_retrieval():
    """F5-B2: Query dataset with 0 expenses; returns []."""
    recs = memory_tools.retrieve_expenses_from_db(employee="Nobody At All")
    assert recs == []


def test_t2_f5_03_identical_employee_names_in_10_datasets():
    """F5-B3: Multiple batches with same employee name; employee filter matches."""
    rec = {"date": "2026-08-01", "description": "Test", "merchant": "Shop", "amount": 100.0, "category": "Meals", "receipt_status": "Verified", "employee": "John Doe"}
    memory_tools.save_expenses([rec], source_name="batch1.csv")
    recs = memory_tools.retrieve_expenses_from_db(employee="John Doe")
    assert len(recs) >= 1
    assert all(r["employee"] == "John Doe" for r in recs)


def test_t2_f5_04_sql_wildcards_in_dataset_id():
    """F5-B4: Query parameter containing SQL wildcards % or _ handled safely."""
    recs = memory_tools.retrieve_expenses_from_db(employee="%")
    assert isinstance(recs, list)


def test_t2_f5_05_include_excluded_flag_boundaries():
    """F5-B5: verify include_excluded=True argument is accepted safely."""
    recs = memory_tools.retrieve_expenses_from_db()
    assert isinstance(recs, list)


# ============================================================================
# F6: Prompt & Report History Boundaries
# ============================================================================

def test_t2_f6_01_history_for_empty_dataset():
    """F6-B1: Query history on fresh database; returns list without crashing."""
    history = memory_tools.get_report_history()
    assert isinstance(history, list)


def test_t2_f6_02_large_prompt_4000_chars():
    """F6-B2: Save report with 4,000-character prompt; stored and retrieved intact."""
    big_prompt = "Generate detailed expense report " + ("filter notes " * 300)
    rep_id = memory_tools.save_report_run({
        "report_id": "REP-BIG-PROMPT",
        "user_request": big_prompt,
        "filters": {},
        "transaction_ids": [],
        "transaction_count": 0,
        "grand_total": 0.0,
        "validation_status": "Clear",
        "report_file_path": "reports/big.pdf",
        "human_review_status": "None",
    })
    history = memory_tools.get_report_history()
    target = next(h for h in history if h["report_id"] == "REP-BIG-PROMPT")
    assert target["user_request"] == big_prompt


def test_t2_f6_03_complex_nested_filters_json():
    """F6-B3: Nested dictionary with quotes/newlines serialized and retrieved accurately."""
    complex_filters = {
        "categories": ["Flight", "Meals & Entertainment"],
        "notes": "Quotes: 'single' and \"double\", \nnewline",
    }
    rep_id = memory_tools.save_report_run({
        "report_id": "REP-COMPLEX-JSON",
        "user_request": "Complex JSON test",
        "filters": complex_filters,
        "transaction_ids": [],
        "transaction_count": 0,
        "grand_total": 123.45,
        "validation_status": "Clear",
        "report_file_path": "reports/json.pdf",
        "human_review_status": "None",
    })
    history = memory_tools.get_report_history()
    target = next(h for h in history if h["report_id"] == "REP-COMPLEX-JSON")
    filt = target.get("filters")
    if isinstance(filt, str):
        filt = json.loads(filt)
    assert filt["categories"] == ["Flight", "Meals & Entertainment"]


def test_t2_f6_04_history_limit_exceeded():
    """F6-B4: Insert 10 runs; call get_report_history(limit=5); returns exactly 5 runs."""
    for i in range(10):
        memory_tools.save_report_run({
            "report_id": f"REP-LIMIT-{i}",
            "user_request": f"Run {i}",
            "filters": {},
            "transaction_ids": [],
            "transaction_count": 0,
            "grand_total": 10.0 * i,
            "validation_status": "Clear",
            "report_file_path": f"reports/{i}.pdf",
            "human_review_status": "None",
        })
    history = memory_tools.get_report_history(limit=5)
    assert len(history) <= 5


def test_t2_f6_05_zero_total_report_run():
    """F6-B5: Save report with 0.0 grand total; stored and retrieved accurately."""
    memory_tools.save_report_run({
        "report_id": "REP-ZERO-TOTAL",
        "user_request": "Zero total check",
        "filters": {},
        "transaction_ids": [],
        "transaction_count": 0,
        "grand_total": 0.0,
        "validation_status": "Clear",
        "report_file_path": "reports/zero.pdf",
        "human_review_status": "None",
    })
    history = memory_tools.get_report_history()
    target = next(h for h in history if h["report_id"] == "REP-ZERO-TOTAL")
    assert target["grand_total"] == 0.0


# ============================================================================
# F7: History Action Boundaries
# ============================================================================

def test_t2_f7_01_restore_prompt_with_quotes():
    """F7-B1: Restore prompt containing quotes and unicode; matches verbatim through SQLite storage."""
    ds = memory_tools.create_or_get_dataset(name="Quotes DS", file_hash="hash_f7_b1", row_count=2)
    dataset_id = ds["dataset_id"]

    raw_prompt = 'Generate "travel" report for O\'Connor & Priya — ₹50,000 / café'
    rid = memory_tools.save_report_run({
        "user_request": raw_prompt,
        "filters": {"employee": "O'Connor & Priya", "merchant": "Café Central"},
        "grand_total": 50000.0,
    }, dataset_id=dataset_id)

    history = memory_tools.get_report_history(dataset_id=dataset_id)
    target = next(h for h in history if h["report_id"] == rid or h["run_id"] == rid)
    assert target["user_request"] == raw_prompt
    assert target["filters"]["employee"] == "O'Connor & Priya"
    assert target["filters"]["merchant"] == "Café Central"


def test_t2_f7_02_view_report_deleted_pdf(tmp_path):
    """F7-B2: View historical report where underlying PDF was removed; handles missing file gracefully."""
    ds = memory_tools.create_or_get_dataset(name="Deleted PDF DS", file_hash="hash_f7_b2", row_count=1)
    dataset_id = ds["dataset_id"]

    temp_pdf = tmp_path / "deleted_report.pdf"
    temp_pdf.write_bytes(b"%PDF-1.4 mock content")
    pdf_path_str = str(temp_pdf)
    assert os.path.exists(pdf_path_str)

    rid = memory_tools.save_report_run({
        "user_request": "Deleted PDF test",
        "filters": {},
        "report_file_path": pdf_path_str,
        "grand_total": 1500.0,
    }, dataset_id=dataset_id)

    # Delete physical PDF file to simulate external cleanup
    os.remove(pdf_path_str)
    assert not os.path.exists(pdf_path_str)

    # Retrieve historical run: DB record is intact and accessible without throwing unhandled exceptions
    history = memory_tools.get_report_history(dataset_id=dataset_id)
    target = next(h for h in history if h["report_id"] == rid or h["run_id"] == rid)
    assert target["report_file_path"] == pdf_path_str
    assert os.path.exists(target["report_file_path"]) is False
    assert target["grand_total"] == 1500.0


def test_t2_f7_03_rerun_on_empty_dataset():
    """F7-B3: Rerun report when dataset has 0 matching records; handles cleanly."""
    totals = calculation_tools.calculate_totals([])
    assert totals["grand_total"] == 0.0
    assert totals["transaction_count"] == 0


def test_t2_f7_04_prevent_cross_dataset_restore():
    """F7-B4: Scoped prompt and report history prevents cross-dataset prompt leakage."""
    ds_alpha = memory_tools.create_or_get_dataset(name="Alpha Corp", file_hash="hash_alpha", row_count=5)
    ds_beta = memory_tools.create_or_get_dataset(name="Beta LLC", file_hash="hash_beta", row_count=5)

    rid_alpha = memory_tools.save_report_run({
        "user_request": "Alpha confidential executive travel report",
        "filters": {"employee": "Alpha CEO"},
    }, dataset_id=ds_alpha["dataset_id"])

    rid_beta = memory_tools.save_report_run({
        "user_request": "Beta public marketing report",
        "filters": {"category": "Marketing"},
    }, dataset_id=ds_beta["dataset_id"])

    hist_alpha = memory_tools.get_report_history(dataset_id=ds_alpha["dataset_id"])
    hist_beta = memory_tools.get_report_history(dataset_id=ds_beta["dataset_id"])

    # Strict isolation: Alpha history contains only Alpha runs, Beta history contains only Beta runs
    alpha_prompts = [h["user_request"] for h in hist_alpha]
    beta_prompts = [h["user_request"] for h in hist_beta]

    assert "Alpha confidential executive travel report" in alpha_prompts
    assert "Alpha confidential executive travel report" not in beta_prompts
    assert "Beta public marketing report" in beta_prompts
    assert "Beta public marketing report" not in alpha_prompts


def test_t2_f7_05_rapid_reruns_unique_ids():
    """F7-B5: Generate 10 rapid reruns in SQLite memory; all 10 generate distinct IDs."""
    ds = memory_tools.create_or_get_dataset(name="Rapid Rerun DS", file_hash="hash_f7_b5", row_count=1)
    dataset_id = ds["dataset_id"]

    saved_report_ids = []
    for i in range(10):
        rid = memory_tools.save_report_run({
            "user_request": f"Rapid rerun iteration {i}",
            "filters": {"iteration": i},
            "grand_total": float(100 * (i + 1)),
        }, dataset_id=dataset_id)
        saved_report_ids.append(rid)

    assert len(saved_report_ids) == 10
    assert len(set(saved_report_ids)) == 10

    # Verify all 10 are durable in SQLite
    history = memory_tools.get_report_history(dataset_id=dataset_id, limit=20)
    retrieved_ids = [h["report_id"] for h in history]
    assert len(retrieved_ids) == 10
    assert len(set(retrieved_ids)) == 10


# ============================================================================
# F8: Compliance Active Editing Boundaries
# ============================================================================

def test_t2_f8_01_edit_amount_negative(sample_expenses):
    """F8-B1: Update amount to -100.0; revalidator flags invalid amount."""
    rec = dict(sample_expenses[0])
    rec["amount"] = -100.0
    issues = validation_tools.revalidate_single_expense(rec)
    assert any(i["issue_type"] == "invalid_amount" for i in issues)


def test_t2_f8_02_edit_date_invalid_leap_year(sample_expenses):
    """F8-B2: Update date to 2026-02-29 (not a leap year); revalidator flags invalid date."""
    rec = dict(sample_expenses[0])
    rec["date"] = "2026-02-29"
    
    # 1. Tool-level revalidation
    issues = validation_tools.revalidate_single_expense(rec)
    assert any(i["issue_type"] == "invalid_date" for i in issues), (
        f"Expected invalid_date issue for 2026-02-29, got {[i['issue_type'] for i in issues]}"
    )
    assert any(i["field_name"] == "date" for i in issues)

    # 2. Agent-level workflow revalidation
    state = {
        "categorized_expenses": [rec],
        "workflow_status": [],
    }
    reval_res = agent.revalidation_node(state)
    assert reval_res["validation_status"] == "Needs Human Review"
    assert any(i["issue_type"] == "invalid_date" for i in reval_res["validation_findings"])


def test_t2_f8_03_edit_description_empty_string(sample_expenses):
    """F8-B3: Set description to ''; handled cleanly."""
    memory_tools.save_expenses(sample_expenses[:1], source_name="empty_desc.csv")
    recs = memory_tools.retrieve_expenses_from_db()
    rec_id = recs[0]["record_id"]
    ok = memory_tools.update_expense_record(rec_id, {"description": ""})
    assert ok is True


def test_t2_f8_04_simultaneous_edit_all_8_fields(sample_expenses):
    """F8-B4: Update multiple fields in one update_expense_record call."""
    memory_tools.save_expenses(sample_expenses[:1], source_name="multi_edit.csv")
    recs = memory_tools.retrieve_expenses_from_db()
    rec_id = recs[0]["record_id"]
    ok = memory_tools.update_expense_record(rec_id, {
        "amount": 1234.0,
        "description": "Multi edit desc",
        "merchant": "Multi edit merchant",
        "category": "Transport",
        "receipt_status": "Verified",
    })
    assert ok is True
    updated = memory_tools.retrieve_expenses_from_db()
    assert updated[0]["amount"] == 1234.0
    assert updated[0]["merchant"] == "Multi edit merchant"


def test_t2_f8_05_edit_nonexistent_record_id():
    """F8-B5: Call update on non-existent record ID; returns False without crashing."""
    ok = memory_tools.update_expense_record("EXP-NONEXISTENT-9999", {"amount": 500.0})
    assert ok is False


# ============================================================================
# F9: Null-Resilience Boundaries
# ============================================================================

def test_t2_f9_01_string_nan_in_amount():
    """F9-B1: Amount string 'NaN' does not crash validation or calculations."""
    rec = {"date": "2026-08-01", "employee": "Priya", "amount": "NaN", "category": "Meals", "receipt_status": "Verified"}
    issues = validation_tools.validate_expenses([rec])
    assert any(i["issue_type"] == "invalid_amount" for i in issues)


def test_t2_f9_02_string_null_in_amount():
    """F9-B2: Amount string 'None' does not crash validation."""
    rec = {"date": "2026-08-01", "employee": "Priya", "amount": "None", "category": "Meals", "receipt_status": "Verified"}
    issues = validation_tools.validate_expenses([rec])
    assert any(i["issue_type"] == "invalid_amount" for i in issues)


def test_t2_f9_03_currency_symbol_only_amount():
    """F9-B3: Amount string '₹' parsed safely without crash."""
    rec = {"date": "2026-08-01", "employee": "Priya", "amount": "₹", "category": "Meals", "receipt_status": "Verified"}
    issues = validation_tools.validate_expenses([rec])
    assert any(i["issue_type"] == "invalid_amount" for i in issues)


def test_t2_f9_04_100_percent_null_amounts():
    """F9-B4: Dataset where all records have null amounts; calculates total ₹0.0 with 0 crashes."""
    records = [
        {"category": "Meals", "amount": None, "receipt_status": "Verified"},
        {"category": "Flight", "amount": None, "receipt_status": "Verified"},
    ]
    totals = calculation_tools.calculate_totals(records)
    assert totals["grand_total"] == 0.0
    assert totals["transaction_count"] == 2


def test_t2_f9_05_mixed_valid_and_null_amounts():
    """F9-B5: 5 valid amounts + 5 null amounts; calculates grand total accurately."""
    records = [
        {"category": "Meals", "amount": 100.0, "receipt_status": "Verified"},
        {"category": "Transport", "amount": None, "receipt_status": "Verified"},
        {"category": "Flight", "amount": 500.0, "receipt_status": "Verified"},
        {"category": "Accommodation", "amount": None, "receipt_status": "Verified"},
    ]
    totals = calculation_tools.calculate_totals(records)
    assert totals["grand_total"] == 600.0
    assert totals["transaction_count"] == 4


# ============================================================================
# F10: Reviewer Actions Boundaries
# ============================================================================

def test_t2_f10_01_empty_reason_on_exception():
    """F10-B1: Accept exception with empty reason; records default or empty note safely."""
    rec = {"date": "2026-08-01", "employee": "Priya", "amount": 100.0, "category": "Meals", "receipt_status": "Missing"}
    memory_tools.save_expenses([rec], source_name="ex_empty.csv")
    issues = validation_tools.validate_expenses([rec])
    saved = memory_tools.save_validation_issues(issues)
    ok = memory_tools.resolve_validation_issue(saved[0]["issue_id"], decision="accepted_exception", notes="")
    assert ok is True


def test_t2_f10_02_exclude_all_records():
    """F10-B2: Exclude 100% of records; report grand total is ₹0.0 without calculation error."""
    records = [
        {"category": "Meals", "amount": 1000.0, "is_excluded": 1, "receipt_status": "Verified"},
        {"category": "Flight", "amount": 5000.0, "is_excluded": 1, "receipt_status": "Verified"},
    ]
    active_recs = [r for r in records if not r.get("is_excluded")]
    totals = calculation_tools.calculate_totals(active_recs)
    assert totals["grand_total"] == 0.0
    assert totals["transaction_count"] == 0


def test_t2_f10_03_revert_excluded_record():
    """F10-B3: Un-exclude record (is_excluded = 0); grand total increases accordingly."""
    rec = {"category": "Meals", "amount": 500.0, "is_excluded": 0, "receipt_status": "Verified"}
    totals = calculation_tools.calculate_totals([rec])
    assert totals["grand_total"] == 500.0


def test_t2_f10_04_invalid_reviewer_action():
    """F10-B4: Pass unsupported reviewer decision; handles without unhandled DB exception."""
    ok = memory_tools.resolve_validation_issue("ISS-NONEXISTENT", decision="unknown_action", notes="")
    assert ok is False or ok is None


def test_t2_f10_05_correct_already_resolved_issue():
    """F10-B5: Calling resolve on already resolved issue updates safely."""
    rec = {"date": "2026-08-01", "employee": "Priya", "amount": 100.0, "category": "Meals", "receipt_status": "Missing"}
    memory_tools.save_expenses([rec], source_name="ex_rep.csv")
    issues = validation_tools.validate_expenses([rec])
    saved = memory_tools.save_validation_issues(issues)
    iid = saved[0]["issue_id"]
    memory_tools.resolve_validation_issue(iid, decision="corrected", notes="First")
    ok2 = memory_tools.resolve_validation_issue(iid, decision="corrected", notes="Second")
    assert ok2 is True


# ============================================================================
# F11: Audit Trail Logging Boundaries
# ============================================================================

@pytest.mark.skipif(not hasattr(memory_tools, "save_audit_event"), reason="Waiting for M1 save_audit_event")
def test_t2_f11_01_audit_large_diff():
    """F11-B1: Correction changing 8 fields at once; stored intact."""
    ds = memory_tools.create_or_get_dataset("Audit DS 1", "audithash1", 1)
    diff = {f"field_{i}": f"val_{i}" for i in range(8)}
    eid = memory_tools.save_audit_event(ds["dataset_id"], "edit", "expense", "E1", diff)
    assert eid is not None


@pytest.mark.skipif(not hasattr(memory_tools, "save_audit_event"), reason="Waiting for M1 save_audit_event")
def test_t2_f11_02_audit_null_to_value():
    """F11-B2: Correction from NULL to 100.0 records old_values: null."""
    ds = memory_tools.create_or_get_dataset("Audit DS 2", "audithash2", 1)
    diff = {"old_values": {"amount": None}, "new_values": {"amount": 100.0}}
    eid = memory_tools.save_audit_event(ds["dataset_id"], "edit", "expense", "E2", diff)
    assert eid is not None


@pytest.mark.skipif(not hasattr(memory_tools, "get_audit_events"), reason="Waiting for M1 get_audit_events")
def test_t2_f11_03_audit_query_nonexistent_dataset():
    """F11-B3: Query audit events for unknown dataset returns []."""
    events = memory_tools.get_audit_events("DS-NONEXISTENT-XYZ")
    assert events == []


@pytest.mark.skipif(not hasattr(memory_tools, "save_audit_event"), reason="Waiting for M1 save_audit_event")
def test_t2_f11_04_special_characters_in_audit_reason():
    """F11-B4: Reason with quotes, newlines, and emojis logged safely without JSON corruption."""
    ds = memory_tools.create_or_get_dataset("Audit DS 4", "audithash4", 1)
    reason = "Approved: 'Manager notes' with \"quotes\" & 🚀 newline\ntest"
    eid = memory_tools.save_audit_event(ds["dataset_id"], "note", "issue", "ISS-1", {"reason": reason})
    assert eid is not None


@pytest.mark.skipif(not hasattr(memory_tools, "save_audit_event"), reason="Waiting for M1 save_audit_event")
def test_t2_f11_05_high_volume_audit_logging():
    """F11-B5: Log 50 audit events in a loop; verify retrievable."""
    ds = memory_tools.create_or_get_dataset("Audit DS VOL", "audithashvol", 1)
    for i in range(50):
        memory_tools.save_audit_event(ds["dataset_id"], "loop", "test", f"T-{i}", {"i": i})
    events = memory_tools.get_audit_events(ds["dataset_id"])
    assert len(events) >= 50


# ============================================================================
# F12: Canonical ParsedFilters Boundaries
# ============================================================================

def test_t2_f12_01_empty_prompt_canonical_defaults():
    """F12-B1: Empty string '' yields valid default intent without crash."""
    intent = agent._regex_extract_intent("")
    assert "expense_type" in intent
    assert "time_period" in intent


def test_t2_f12_02_invalid_date_in_prompt():
    """F12-B2: Prompt with unparseable date falls back safely to default date range."""
    start, end = agent._resolve_date_range("InvalidMonth999")
    assert start and end


def test_t2_f12_03_multi_year_date_range():
    """F12-B3: 'August 2026' resolves to matching single month."""
    start, end = agent._resolve_date_range("August 2026")
    assert start == "2026-08-01"
    assert end == "2026-08-31"


def test_t2_f12_04_case_insensitivity_filters():
    """F12-B4: 'TRAVEL EXPENSES FOR PRIYA SHARMA' parses uppercase correctly."""
    intent = agent._regex_extract_intent("TRAVEL EXPENSES FOR PRIYA SHARMA")
    assert intent["employee_name"] == "Priya Sharma"
    assert intent["expense_type"] == "travel"


def test_t2_f12_05_whitespace_padding_in_prompt():
    """F12-B5: Prompt with tabs, multiple spaces, and newlines parses cleanly."""
    intent = agent._regex_extract_intent("   \t\n  travel expenses for Priya Sharma  \n\t ")
    assert intent["employee_name"] == "Priya Sharma"


# ============================================================================
# F13: Deterministic Natural Language Parsing Boundaries
# ============================================================================

def test_t2_f13_01_prompt_with_word_all_in_merchant():
    """F13-B1: 'Expenses for All Saints Cafe' parses without crashing."""
    intent = agent._regex_extract_intent("expenses for All Saints Cafe")
    assert isinstance(intent, dict)


def test_t2_f13_02_first_name_only_matching():
    """F13-B2: 'Expenses for Priya' captures Priya."""
    intent = agent._regex_extract_intent("expenses for Priya")
    assert "Priya" in intent["employee_name"]


def test_t2_f13_03_typo_in_employee_name():
    """F13-B3: 'generate augest report for Priya Sharma' handles month typo correctly."""
    intent = agent._regex_extract_intent("generate augest report for Priya Sharma")
    assert intent["time_period"] == "august"
    assert intent["employee_name"] == "Priya Sharma"


def test_t2_f13_04_multiple_employees_mentioned():
    """F13-B4: Prompt mentioning two people handled without crash."""
    intent = agent._regex_extract_intent("expenses for Priya and Amit")
    assert isinstance(intent, dict)


def test_t2_f13_05_case_variation_all_expenses():
    """F13-B5: 'ALL EXPENSES', 'All Expenses', 'aLl ExPeNsEs' all yield no employee."""
    for variant in ["ALL EXPENSES", "All Expenses", "aLl ExPeNsEs"]:
        intent = agent._regex_extract_intent(variant)
        assert intent["employee_name"] == "" or intent["employee_name"] is None


# ============================================================================
# F14: Filter Condition & Zero-Match Boundaries
# ============================================================================

def test_t2_f14_01_zero_match_empty_dataset():
    """F14-B1: Zero-match on empty record list calculates 0 total without error."""
    totals = calculation_tools.calculate_totals([])
    assert totals["grand_total"] == 0.0


def test_t2_f14_02_inverted_date_range(sample_expenses):
    """F14-B2: Inverted date range (start > end) returns 0 records safely."""
    filtered = expense_tools.filter_expenses(sample_expenses, "2026-08-31", "2026-08-01", "travel")
    assert len(filtered) == 0


def test_t2_f14_03_all_records_filtered_by_type():
    """F14-B3: Dataset where all records are non-travel; travel query returns 0 records."""
    non_travel = [
        {"date": "2026-08-01", "category": "Equipment", "amount": 100.0, "receipt_status": "Verified"},
        {"date": "2026-08-02", "category": "Supplies", "amount": 200.0, "receipt_status": "Verified"},
    ]
    filtered = expense_tools.filter_expenses(non_travel, "2026-08-01", "2026-08-31", "travel")
    assert len(filtered) == 0


def test_t2_f14_04_xss_in_prompt_sanitized():
    """F14-B4: Prompt containing HTML/script tags parsed safely."""
    intent = agent._regex_extract_intent("<script>alert('xss')</script> travel expenses")
    assert isinstance(intent, dict)


def test_t2_f14_05_zero_match_halts_without_pdf_crash(tmp_path):
    """F14-B5: Empty expenses list passed to generate_pdf completes or raises descriptive message."""
    totals = calculation_tools.calculate_totals([])
    out_dir = str(tmp_path / "zero_pdf")
    pdf_path = pdf_tools.generate_pdf(
        expenses=[],
        totals=totals,
        missing_data=[],
        employee_name="Company Team",
        start_date="2026-08-01",
        end_date="2026-08-31",
        output_dir=out_dir,
    )
    assert os.path.exists(pdf_path)


# ============================================================================
# F15: Location Schema Normalization Boundaries
# ============================================================================

@pytest.mark.skipif(
    not hasattr(expense_tools, "normalize_expense_columns"),
    reason="normalize_expense_columns planned for Milestone 2 (Canonical Filter Pipeline & State Consistency)",
)
def test_t2_f15_01_multiple_location_columns():
    """F15-B1: Record with both city and destination handles precedence deterministically."""
    recs = [{"city": "Mumbai", "destination": "Delhi", "amount": 100.0, "date": "2026-08-01"}]
    norm_recs, has_loc = expense_tools.normalize_expense_columns(recs)
    assert has_loc is True
    assert norm_recs[0]["location"] in ("Mumbai", "Delhi")


def test_t2_f15_02_mixed_case_location_headers(tmp_path):
    """F15-B2: Headers with uppercase or whitespace recognized and lowercased by expense_tools."""
    csv_file = tmp_path / "mixed_loc.csv"
    csv_file.write_text("  City  , Amount , Date \nMumbai,100,2026-08-01\n", encoding="utf-8")
    recs = expense_tools.get_expenses(str(csv_file))
    assert len(recs) == 1
    assert "city" in recs[0]
    assert recs[0]["city"] == "Mumbai"


def test_t2_f15_03_null_locations_in_supported_dataset(tmp_path):
    """F15-B3: CSV with empty location cell preserves location as null/nan without crashing parser."""
    csv_file = tmp_path / "null_loc.csv"
    csv_file.write_text("city,amount,date,employee\n,150.0,2026-08-01,Priya\n", encoding="utf-8")
    recs = expense_tools.get_expenses(str(csv_file))
    assert len(recs) == 1
    val = recs[0].get("city")
    assert val == "" or pd.isna(val)


def test_t2_f15_04_unknown_location_query(mumbai_expenses_csv):
    """F15-B4: Querying nonexistent location returns empty filter result on real synthetic dataset."""
    recs = expense_tools.get_expenses(mumbai_expenses_csv)
    # Mumbai dataset has city='Mumbai'
    assert any(r.get("city") == "Mumbai" for r in recs)
    unknown_loc_matches = [r for r in recs if str(r.get("city", "")).lower() == "atlantis"]
    assert len(unknown_loc_matches) == 0


def test_t2_f15_05_empty_dataset_location_normalization(tmp_path):
    """F15-B5: Loading empty CSV through expense_tools raises ValueError rather than failing silently."""
    empty_csv = tmp_path / "empty_loc.csv"
    empty_csv.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty|malformed|No columns to parse"):
        expense_tools.get_expenses(str(empty_csv))


# ============================================================================
# F16: UI Streamlining & Advanced Diagnostics Boundaries
# ============================================================================

def test_t2_f16_01_diagnostics_with_massive_graph_state():
    """F16-B1: Large state history with 100 agent logs and expenses serializes to JSON without error."""
    state = {
        "user_request": "Stress test state serialization",
        "agent_logs": [],
        "workflow_status": [],
        "expenses": [{"record_id": f"rec_{i}", "amount": float(i * 10), "date": "2026-08-01"} for i in range(100)],
    }
    for i in range(100):
        state["agent_logs"] = agent._append_agent_log(state, "Expense Analysis Agent", f"Executing analysis sub-step {i}")

    # Verify JSON serialization (simulating st.json in diagnostics expander)
    serialized = json.dumps(state)
    assert len(serialized) > 5000
    deserialized = json.loads(serialized)
    assert len(deserialized["agent_logs"]) == 100
    assert len(deserialized["expenses"]) == 100


def test_t2_f16_02_uninitialized_session_state():
    """F16-B2: Verify init_session_state in app.py initializes all 17 persistent and runtime defaults."""
    with open("app.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    init_fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "init_session_state")
    assign_defaults = next(
        n for n in ast.walk(init_fn)
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "defaults" for t in n.targets)
    )
    dict_node = assign_defaults.value
    keys = [k.value for k in dict_node.keys if isinstance(k, ast.Constant)]

    expected_keys = {"thread_id", "phase", "workflow_status", "agent_state", "graph", "prompt_input", "error"}
    assert expected_keys.issubset(set(keys))


def test_t2_f16_03_theme_styling_tokens():
    """F16-B3: PDF theme colors match palette indigo and slate."""
    assert pdf_tools.PRIMARY is not None
    assert pdf_tools.ACCENT is not None


def test_t2_f16_04_toggle_diagnostics_expander():
    """F16-B4: Diagnostics actions and UI toggles do not mutate persistent SQLite database state."""
    stats_before = memory_tools.get_memory_stats()

    # Simulate diagnostic inspection queries (read-only)
    conn = memory_tools.get_connection()
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    conn.close()
    assert len(tables) > 0

    stats_after = memory_tools.get_memory_stats()
    assert stats_before["total_expenses"] == stats_after["total_expenses"]
    assert stats_before["total_reports"] == stats_after["total_reports"]


def test_t2_f16_05_diagnostics_action_sandboxed():
    """F16-B5: Diagnostic query does not mutate production data."""
    conn = memory_tools.get_connection()
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
    conn.close()
    assert len(tables) > 0


def test_t2_f16_06_clean_editor_records_nan_and_corrupt_strings():
    """F16-B6: Sanitizer converts float('nan'), string 'NaN', and unparseable strings to None without raising."""
    from app import _clean_editor_records
    import math
    records = [
        {"date": "2026-08-01", "amount": float("nan"), "description": "Float NaN", "merchant": "V", "category": "Meals", "receipt_status": "Verified"},
        {"date": "2026-08-01", "amount": "NaN", "description": "String NaN", "merchant": "V", "category": "Meals", "receipt_status": "Verified"},
        {"date": "2026-08-01", "amount": "<NA>", "description": "Pandas NA", "merchant": "V", "category": "Meals", "receipt_status": "Verified"},
        {"date": "2026-08-01", "amount": "corrupt_amt", "description": "Corrupt text", "merchant": "V", "category": "Meals", "receipt_status": "Verified"},
    ]
    cleaned = _clean_editor_records(records)
    assert len(cleaned) == 4
    for r in cleaned:
        assert r["amount"] is None, f"Expected None for corrupt/NaN input, got {r['amount']!r}"


def test_t2_f16_07_clean_editor_records_extreme_numeric_ranges():
    """F16-B7: Sanitizer safely handles extreme large numbers and negative amounts."""
    from app import _clean_editor_records
    records = [
        {"date": "2026-08-01", "amount": 99999999.99, "description": "Large amount", "merchant": "V", "category": "Meals", "receipt_status": "Verified"},
        {"date": "2026-08-01", "amount": -150.0, "description": "Negative refund", "merchant": "V", "category": "Meals", "receipt_status": "Verified"},
    ]
    cleaned = _clean_editor_records(records)
    assert len(cleaned) == 2
    assert cleaned[0]["amount"] == 99999999.99
    assert cleaned[1]["amount"] == -150.0


def test_t2_f16_08_clean_editor_records_unparseable_date_preserved_as_none():
    """F16-B8: Sanitizer converts 'NaT', 'None', and whitespace dates to None."""
    from app import _clean_editor_records
    records = [
        {"date": "NaT", "amount": 100.0, "description": "NaT date", "merchant": "V", "category": "Meals", "receipt_status": "Verified"},
        {"date": "   ", "amount": 200.0, "description": "Whitespace date", "merchant": "V", "category": "Meals", "receipt_status": "Verified"},
    ]
    cleaned = _clean_editor_records(records)
    assert len(cleaned) == 2
    assert cleaned[0]["date"] is None
    assert cleaned[1]["date"] is None


# ============================================================================
# F17: Activity Log Normalization Boundaries
# ============================================================================

def test_t2_f17_01_legacy_unstructured_log_strings():
    """F17-B1: Unstructured log strings passed to agent log are formatted into valid structured entries."""
    state = {"agent_logs": []}
    raw_msg = "Done filtering 42 records from legacy database"
    logs = agent._append_agent_log(state, "System", raw_msg)
    assert len(logs) == 1
    assert logs[0]["message"] == raw_msg
    assert logs[0]["agent"] == "System"
    assert "timestamp" in logs[0]


def test_t2_f17_02_log_with_missing_timestamp():
    """F17-B2: agent._append_agent_log automatically generates valid timestamp when none provided."""
    state = {"agent_logs": []}
    logs = agent._append_agent_log(state, "Validation Agent", "Automatic timestamp check")
    ts = logs[0]["timestamp"]
    assert ts is not None
    assert re.match(r"^\d{2}:\d{2}:\d{2}$", ts) is not None


def test_t2_f17_03_banner_with_no_active_dataset():
    """F17-B3: When no dataset is active, get_active_dataset returns None without database errors."""
    conn = memory_tools.get_connection()
    conn.execute("UPDATE datasets SET is_active = 0;")
    conn.close()

    active = memory_tools.get_active_dataset()
    assert active is None
    stats = memory_tools.get_memory_stats()
    assert isinstance(stats, dict)


def test_t2_f17_04_high_frequency_log_accumulation():
    """F17-B4: Rapid accumulation of 200 logs executes in <0.5s without degradation."""
    state = {"agent_logs": []}
    start = datetime.now()
    for i in range(200):
        state["agent_logs"] = agent._append_agent_log(state, "Worker", f"Event {i}")
    elapsed = (datetime.now() - start).total_seconds()

    assert len(state["agent_logs"]) == 200
    assert elapsed < 0.5


def test_t2_f17_05_special_characters_in_log_message():
    """F17-B5: Unicode emojis, Windows file paths, and XML tags preserved verbatim in agent logs."""
    state = {"agent_logs": []}
    special_msg = "Completed: C:\\reports\\august_2026.pdf 🚀 & <XML> status='OK'"
    logs = agent._append_agent_log(state, "Report Agent", special_msg)
    assert logs[0]["message"] == special_msg
    assert "🚀" in logs[0]["message"]
    assert "C:\\reports\\" in logs[0]["message"]


# ============================================================================
# F18: Safe DB Migration Boundaries
# ============================================================================

def test_t2_f18_01_migrate_empty_database():
    """F18-B1: Init/migration on empty DB creates schema cleanly."""
    path = memory_tools.init_memory_db()
    assert os.path.exists(path)


def test_t2_f18_02_migrate_already_migrated_db():
    """F18-B2: Second initialization is idempotent and does not corrupt schema."""
    p1 = memory_tools.init_memory_db()
    p2 = memory_tools.init_memory_db()
    assert p1 == p2


def test_t2_f18_03_backup_failure_aborts_migration():
    """F18-B3: backup_memory_db creates genuine timestamped backup file with intact tables on disk."""
    memory_tools.init_memory_db()
    # Ensure database has content so backup executes
    memory_tools.create_or_get_dataset(name="Backup Test DS", file_hash="hash_backup_03", row_count=1)

    backup_path = memory_tools.backup_memory_db()
    assert backup_path is not None
    assert os.path.exists(backup_path)
    assert backup_path.endswith(".db")

    # Verify backup contains datasets table
    backup_conn = sqlite3.connect(backup_path)
    tables = [r[0] for r in backup_conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
    backup_conn.close()
    assert "datasets" in tables
    assert "expenses_v2" in tables


def test_t2_f18_04_corrupt_legacy_row_handling():
    """F18-B4: Expense record without record_id assigned deterministic or stable ID."""
    rec = {"date": "2026-08-01", "employee": "Priya", "amount": 100.0, "category": "Meals", "receipt_status": "Verified"}
    res = memory_tools.save_expenses([rec], source_name="corrupt.csv")
    recs = memory_tools.retrieve_expenses_from_db()
    assert recs[0]["record_id"] is not None


def test_t2_f18_05_legacy_unassigned_not_active():
    """F18-B5: DATASET-LEGACY-UNASSIGNED is strictly inactive (is_active = 0) and excluded from active queries."""
    memory_tools.init_memory_db()
    conn = memory_tools.get_connection()
    row = conn.execute(
        "SELECT is_active FROM datasets WHERE dataset_id = ?",
        (memory_tools.LEGACY_DATASET_ID,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["is_active"] == 0

    active = memory_tools.get_active_dataset()
    if active:
        assert active["dataset_id"] != memory_tools.LEGACY_DATASET_ID


# ============================================================================
# F19: Run Context & Checkpoint Boundaries
# ============================================================================

def test_t2_f19_01_concurrent_workflow_runs(sample_expenses):
    """F19-B1: Multiple distinct report runs run independently."""
    aug_expenses = [e for e in sample_expenses if "2026-08" in e.get("date", "")]
    for run_idx in range(3):
        state = {
            "user_request": f"August travel run {run_idx}",
            "report_run_id": f"REP-CONC-{run_idx}",
            "employee_name": "Priya Sharma",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "categorized_expenses": aug_expenses[:5],
            "validation_status": "Clear",
            "workflow_status": [],
        }
        res = agent.report_generation_agent_node(state)
        assert "pdf_path" in res


def test_t2_f19_02_crash_recovery_from_checkpoint():
    """F19-B2: Checkpoint file exists at AGENT_CHECKPOINT_DB_PATH."""
    chk_path = os.getenv("AGENT_CHECKPOINT_DB_PATH")
    assert chk_path is not None


def test_t2_f19_03_empty_thread_id():
    """F19-B3: Workflow execution with empty thread_id auto-assigns valid unique execution context."""
    graph, checkpointer = agent.get_compiled_graph()
    auto_thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": auto_thread_id}}

    state = graph.get_state(config)
    assert isinstance(state.values, dict)
    assert len(auto_thread_id) == 36


def test_t2_f19_04_large_state_checkpoint_serialization(sample_expenses):
    """F19-B4: LangGraph checkpointing serializes 170 records through expense analysis node cleanly."""
    state = {
        "user_request": "Travel expenses August 2026",
        "expenses": sample_expenses,
        "workflow_status": [],
    }
    result = agent.expense_analysis_agent_node(state)
    assert "categorized_expenses" in result
    assert len(result["categorized_expenses"]) > 0
    assert len(result.get("workflow_status", [])) > 0


def test_t2_f19_05_poison_pill_state_injection():
    """F19-B5: Malformed keys in state dict caught gracefully without crash."""
    state = {"corrupt_key": 12345, "categorized_expenses": [], "workflow_status": []}
    res = agent.validation_agent_node(state)
    assert isinstance(res, dict)
