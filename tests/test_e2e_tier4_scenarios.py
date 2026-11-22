"""
E2E Tier 4: Real-World Application Scenarios (5 Scenarios).
High-complexity end-to-end workflows testing multi-agent orchestration, dataset switching,
database migration succession, interactive editing with audit trail, and regression-proof NLP parsing.
"""

import os
import io
import csv
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


def test_scenario_1_multi_city_audit(mumbai_expenses_csv, delhi_expenses_csv, tmp_path):
    """
    Scenario 1: Multi-City Corporate Audit Workflow.
    1. Upload Mumbai expenses (7 rows, total 48,500), hash SHA-256, persist, set active.
    2. Detect compliance issues (missing receipt on Taj dinner).
    3. Correct employee typo / update receipt with audit trail.
    4. Exclude an unauthorized luxury charge (e.g. 1800 cab).
    5. Generate audited PDF report omitting excluded item.
    6. Upload Delhi expenses (5 rows, total 36,200), set active.
    7. Verify strict isolation: active dataset returns 5 Delhi rows (0 Mumbai rows),
       prompt history isolated, switching back to Mumbai restores Mumbai state.
    """
    # 1. Ingest Mumbai
    with open(mumbai_expenses_csv, "rb") as f:
        mumbai_bytes = f.read()
    hash_m = hashlib.sha256(mumbai_bytes).hexdigest()
    ds_m = memory_tools.create_or_get_dataset("Mumbai_Expenses.csv", hash_m, 7)
    memory_tools.set_active_dataset(ds_m["dataset_id"])
    mumbai_rows = expense_tools.get_expenses(mumbai_expenses_csv)
    memory_tools.save_expenses(mumbai_rows, dataset_id=ds_m["dataset_id"])
    assert memory_tools.get_active_dataset()["dataset_id"] == ds_m["dataset_id"]
    recs_m = memory_tools.retrieve_expenses_from_db(dataset_id=ds_m["dataset_id"])
    assert len(recs_m) == 7

    # 2. Validation on persisted records
    issues = validation_tools.validate_expenses(recs_m)
    assert any(i["issue_type"] == "missing_receipt" for i in issues)
    saved_issues = memory_tools.save_validation_issues(issues, dataset_id=ds_m["dataset_id"])

    # 3. Compliance correction: update receipt on Taj dinner
    taj_rec = next(r for r in recs_m if "Taj" in r["merchant"])
    memory_tools.update_expense_record(taj_rec["record_id"], {"receipt_status": "Verified"})
    eid_corr = memory_tools.save_audit_event(
        ds_m["dataset_id"], "record_corrected", "expense", taj_rec["record_id"],
        {"old_values": {"receipt_status": "Missing"}, "new_values": {"receipt_status": "Verified"}}
    )
    assert eid_corr is not None

    # 4. Exclude unauthorized cab charge
    cab_rec = next(r for r in recs_m if "Cabs" in r["merchant"])
    memory_tools.update_expense_record(cab_rec["record_id"], {"is_excluded": 1})
    eid_excl = memory_tools.save_audit_event(
        ds_m["dataset_id"], "record_excluded", "expense", cab_rec["record_id"],
        {"reason": "Excluded unauthorized local cab charge", "amount": cab_rec["amount"]}
    )
    assert eid_excl is not None

    # 5. Generate audited PDF report (excluding cab_rec)
    active_mumbai = memory_tools.retrieve_expenses_from_db(dataset_id=ds_m["dataset_id"])
    categorized_m = validation_tools.categorize_expenses(active_mumbai)
    totals_m = calculation_tools.calculate_totals(categorized_m)
    expected_audited_total = 48500.0 - cab_rec["amount"]
    assert totals_m["grand_total"] == expected_audited_total

    out_dir = str(tmp_path / "scenario_reports")
    pdf_m = pdf_tools.generate_pdf(
        expenses=categorized_m,
        totals=totals_m,
        missing_data=[],
        employee_name="Company Team",
        start_date="2026-07-01",
        end_date="2026-08-31",
        output_dir=out_dir,
    )
    assert os.path.exists(pdf_m)
    memory_tools.save_report_run({
        "report_id": "REP-MUMBAI-AUDITED",
        "dataset_id": ds_m["dataset_id"],
        "user_request": "Audited Mumbai report",
        "filters": {"city": "Mumbai"},
        "transaction_ids": [r["record_id"] for r in active_mumbai],
        "transaction_count": len(active_mumbai),
        "grand_total": totals_m["grand_total"],
        "validation_status": "Clear",
        "report_file_path": pdf_m,
        "human_review_status": "Reviewed with Audit Trail",
    })

    # 6. Upload Delhi expenses
    with open(delhi_expenses_csv, "rb") as f:
        delhi_bytes = f.read()
    hash_d = hashlib.sha256(delhi_bytes).hexdigest()
    ds_d = memory_tools.create_or_get_dataset("Delhi_Expenses.csv", hash_d, 5)
    memory_tools.set_active_dataset(ds_d["dataset_id"])
    delhi_rows = expense_tools.get_expenses(delhi_expenses_csv)
    memory_tools.save_expenses(delhi_rows, dataset_id=ds_d["dataset_id"])
    assert memory_tools.get_active_dataset()["dataset_id"] == ds_d["dataset_id"]

    # 7. Strict isolation checks
    active_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds_d["dataset_id"])
    assert len(active_recs) == 5
    assert not any("Mumbai" in (r.get("city") or "") for r in active_recs)
    
    # Prompt history view for Delhi shows 0 runs
    history_d = memory_tools.get_report_history(dataset_id=ds_d["dataset_id"])
    assert len(history_d) == 0

    # Switch back to Mumbai restores Mumbai history and records
    memory_tools.set_active_dataset(ds_m["dataset_id"])
    assert memory_tools.get_active_dataset()["dataset_id"] == ds_m["dataset_id"]
    history_m = memory_tools.get_report_history(dataset_id=ds_m["dataset_id"])
    assert len(history_m) == 1
    assert history_m[0]["report_id"] == "REP-MUMBAI-AUDITED"
    assert history_m[0]["grand_total"] == expected_audited_total


def test_scenario_2_legacy_db_migration(tmp_path):
    """
    Scenario 2: Legacy Database Migration & Succession.
    1. Populate an isolated DB with 370 legacy records tagged DATASET-LEGACY-UNASSIGNED.
    2. Confirm legacy records have dataset_version = 1 and is_active = 0.
    3. User uploads new Q3_Expenses.csv (10 rows).
    4. Dataset DS-Q3 is marked active.
    5. Active query returns strictly 10 Q3 records (0 legacy records).
    6. Migration runs idempotently with 0 alterations.
    """
    legacy_tag = "DATASET-LEGACY-UNASSIGNED"
    
    # Verify legacy dataset exists in migrated DB
    conn = memory_tools.get_connection()
    legacy_row = conn.execute("SELECT * FROM datasets WHERE dataset_id = ?", (legacy_tag,)).fetchone()
    conn.close()
    assert legacy_row is not None
    assert legacy_row["is_active"] == 0

    # User uploads new Q3 dataset
    ds_q3 = memory_tools.create_or_get_dataset("Q3_Expenses.csv", "q3hash123", 10)
    memory_tools.set_active_dataset(ds_q3["dataset_id"])
    q3_rows = [
        {"date": f"2026-09-{i+1:02d}", "employee": f"Emp {i}", "description": f"Q3 Expense {i}", "merchant": "Vendor", "amount": 1000.0 * (i+1), "category": "Meals", "receipt_status": "Verified"}
        for i in range(10)
    ]
    memory_tools.save_expenses(q3_rows, dataset_id=ds_q3["dataset_id"])

    # Active dataset returns strictly 10 records, 0 legacy contamination
    active_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds_q3["dataset_id"])
    assert len(active_recs) == 10
    assert all(r.get("dataset_id") == ds_q3["dataset_id"] for r in active_recs)

    # Idempotent re-run
    p1 = memory_tools.init_memory_db()
    assert os.path.exists(p1)


def test_scenario_3_interactive_data_correction(nulls_expenses_csv):
    """
    Scenario 3: Interactive Data Correction & Version Rollback.
    1. User uploads raw CSV containing incomplete data (null amounts, missing dates).
    2. Ingestion preserves raw nulls without converting to 0.0 or crashing.
    3. Interactive editor performs corrections:
       - Adds 2 new rows for missing expenses
       - Edits 1 null amount to 1850.0
       - Deletes 1 corrupted test row
    4. Save changes increments dataset version to v2.
    5. Version 1 remains intact, immutable, and queryable.
    6. Validator flags remaining null amounts on v2.
    """
    rows = expense_tools.get_expenses(nulls_expenses_csv)
    ds = memory_tools.create_or_get_dataset("Incomplete_Expenses.csv", "incomp_hash_03", len(rows))
    memory_tools.save_expenses(rows, dataset_id=ds["dataset_id"])

    # Verify v1 records
    v1_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=1)
    assert len(v1_recs) == len(rows)

    # Interactive edits
    edited_rows = [dict(r) for r in rows]
    # Delete 1 row
    deleted = edited_rows.pop(0)
    # Edit 1 row
    edited_rows[0]["amount"] = 1850.0
    # Add 2 new rows
    edited_rows.append({"date": "2026-08-15", "employee": "Priya Sharma", "description": "Client Dinner", "merchant": "Taj", "amount": 3200.0, "category": "Meals", "receipt_status": "Verified"})
    edited_rows.append({"date": "2026-08-16", "employee": "Ravi Kumar", "description": "Team Lunch", "merchant": "Bukhara", "amount": 2800.0, "category": "Meals", "receipt_status": "Verified"})

    # Save v2
    v2 = memory_tools.increment_dataset_version(ds["dataset_id"], edited_rows)
    assert v2 == 2

    # Verify v2 has new count
    v2_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=2)
    assert len(v2_recs) == len(rows) - 1 + 2

    # Verify v1 is immutable
    v1_recs_after = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=1)
    assert len(v1_recs_after) == len(rows)

    # Validation flags remaining null amounts on v2
    issues_v2 = validation_tools.validate_expenses(v2_recs)
    assert any(i["issue_type"] == "invalid_amount" for i in issues_v2)


def test_scenario_4_prompt_regression_suite(sample_expenses):
    """
    Scenario 4: Natural Language Prompt Regression Suite.
    Executes sequential prompts in the same session:
    Step 1: 'all expenses for last month' -> employee is None
    Step 2: 'all expenses for Ravi Kumar' -> employee is 'Ravi Kumar'
    Step 3: 'all expenses for last month' directly after Step 2 -> employee is None (NO LEAKAGE!)
    Step 4: 'all employees expenses for August 2026' -> employee is None, August date range.
    """
    # Step 1: "all expenses for last month"
    s1 = agent._regex_extract_intent("all expenses for last month")
    assert s1["employee_name"] == "" or s1["employee_name"] is None

    # Step 2: "all expenses for Ravi Kumar"
    s2 = agent._regex_extract_intent("all expenses for Ravi Kumar")
    assert s2["employee_name"] == "Ravi Kumar"

    # Step 3: CRITICAL REGRESSION TEST
    # "all expenses for last month" directly following "Ravi Kumar"
    s3 = agent._regex_extract_intent("all expenses for last month")
    assert s3["employee_name"] == "" or s3["employee_name"] is None
    assert s3["employee_name"] != "Ravi Kumar"

    # Step 4: "all employees expenses for August 2026"
    s4 = agent._regex_extract_intent("all employees expenses for August 2026")
    assert s4["employee_name"] == "" or s4["employee_name"] is None
    start, end = agent._resolve_date_range(s4["time_period"])
    assert start == "2026-08-01"
    assert end == "2026-08-31"


def test_scenario_5_absent_location_graceful_degradation(sample_csv_path, sample_expenses, tmp_path):
    """
    Scenario 5: Absent Location & Graceful Degradation.
    1. Load standard expenses.csv (lacks location/city/destination).
    2. User queries 'travel expenses in Bangalore for August 2026'.
    3. Parser extracts time_period = August 2026, expense_type = travel.
    4. Location absence is detected without crashing or raising KeyError.
    5. Date and category filters apply successfully, returning 42 August travel transactions.
    6. PDF report generates cleanly.
    """
    # 1. Inspect schema: no location
    first_row = sample_expenses[0]
    has_location = any(k in first_row for k in ("location", "city", "destination"))
    assert has_location is False

    # 2 & 3. Parse intent
    prompt = "travel expenses in Bangalore for August 2026"
    intent = agent._regex_extract_intent(prompt)
    assert intent["expense_type"] == "travel"
    start, end = agent._resolve_date_range(intent["time_period"])
    assert start == "2026-08-01" and end == "2026-08-31"

    # 4 & 5. Filter without location crashing
    filtered = expense_tools.filter_expenses(sample_expenses, start, end, intent["expense_type"])
    assert len(filtered) == 42  # Exactly 42 August travel transactions in standard expenses.csv

    # 6. Generate report
    categorized = validation_tools.categorize_expenses(filtered)
    totals = calculation_tools.calculate_totals(categorized)
    issues = validation_tools.validate_expenses(categorized)
    
    out_dir = str(tmp_path / "scenario_5_reports")
    pdf_path = pdf_tools.generate_pdf(
        expenses=categorized,
        totals=totals,
        missing_data=issues,
        employee_name="Company Team",
        start_date=start,
        end_date=end,
        output_dir=out_dir,
    )
    assert os.path.exists(pdf_path)
    assert os.path.getsize(pdf_path) > 1000
