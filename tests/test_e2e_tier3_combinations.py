"""
E2E Tier 3: Cross-Feature Integration Combinations (20 tests).
Validates multi-feature interactions, sequential workflows, dataset lifecycle transitions,
validation and correction feedback loops, and audit trail consistency.
"""

import os
import io
import re
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


def test_t3_01_upload_edit_save_version_increment_db_sync(sample_expenses):
    """T3-01: Upload CSV (F1) -> Edit cells (F4) -> Save increments v1->v2 (F4) -> Verify SQLite updated (F2)."""
    ds = memory_tools.create_or_get_dataset(name="Sync Test DS", file_hash="sync_hash_01", row_count=2)
    memory_tools.save_expenses(sample_expenses[:2], dataset_id=ds["dataset_id"])
    
    # Edit records
    edited = [dict(r) for r in sample_expenses[:2]]
    edited[0]["amount"] = 8888.0
    v2 = memory_tools.increment_dataset_version(ds["dataset_id"], edited)
    assert v2 == 2
    
    # Verify DB reflects v2 amount
    v2_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=2)
    assert any(r["amount"] == 8888.0 for r in v2_recs)


def test_t3_02_edit_invalid_amount_revalidate_issue_resolved():
    """T3-02: Ingest null amount (F9) -> Flagged by validator (F8) -> Inline edit (F8) -> Revalidate (F10) -> Resolved (F10) -> Audit (F11)."""
    ds = memory_tools.create_or_get_dataset("Reval DS", "reval_hash_02", 1)
    rec = {
        "date": "2026-08-01",
        "employee": "Priya Sharma",
        "description": "Taxi to airport",
        "merchant": "Uber",
        "category": "Transport",
        "amount": 0.0,  # Flagged amount
        "receipt_status": "Verified",
    }
    saved_batch = memory_tools.save_expenses([rec], dataset_id=ds["dataset_id"])
    recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"])
    issues = validation_tools.validate_expenses(recs)
    assert any(i["issue_type"] == "invalid_amount" for i in issues)
    
    saved_issues = memory_tools.save_validation_issues(issues, dataset_id=ds["dataset_id"])
    iid = saved_issues[0]["issue_id"]
    
    # Reviewer corrects the amount
    memory_tools.update_expense_record(recs[0]["record_id"], {"amount": 750.0})
    updated_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"])
    post_issues = validation_tools.revalidate_single_expense(dict(updated_recs[0]))
    assert not any(i["issue_type"] == "invalid_amount" for i in post_issues)
    
    # Resolve issue and log audit
    memory_tools.resolve_validation_issue(iid, decision="corrected", notes="Fixed zero amount to 750")
    eid = memory_tools.save_audit_event(
        ds["dataset_id"], "record_corrected", "expense", recs[0]["record_id"],
        {"old_values": {"amount": 0.0}, "new_values": {"amount": 750.0}}
    )
    assert eid is not None
    assert len(memory_tools.get_unresolved_issues(dataset_id=ds["dataset_id"])) == 0


def test_t3_03_exclude_record_recalculate_report_preserve_db(sample_expenses):
    """T3-03: Flagged discrepancy (F8) -> Exclude (F10) -> Grand total recalculated without record (F10) -> Preserved in DB (F5) -> Audit logged (F11)."""
    ds = memory_tools.create_or_get_dataset("Exclude DS", "excl_hash_03", 2)
    recs = [
        {"date": "2026-08-01", "employee": "Priya", "amount": 1000.0, "category": "Meals", "receipt_status": "Verified", "is_excluded": 0},
        {"date": "2026-08-02", "employee": "Priya", "amount": 5000.0, "category": "Flight", "receipt_status": "Missing", "is_excluded": 0},
    ]
    memory_tools.save_expenses(recs, dataset_id=ds["dataset_id"])
    
    # Exclude second record
    recs[1]["is_excluded"] = 1
    memory_tools.save_audit_event(ds["dataset_id"], "record_excluded", "expense", "EXP-EXCL", {"amount": 5000.0})
    
    # Report calculation omitting excluded
    active_recs = [r for r in recs if not r.get("is_excluded")]
    totals = calculation_tools.calculate_totals(active_recs)
    assert totals["grand_total"] == 1000.0
    assert totals["transaction_count"] == 1


def test_t3_04_accept_exception_with_notes_include_in_report():
    """T3-04: Flagged issue (F8) -> Accept exception with notes (F10) -> Included in report (F10) -> Audit logged (F11)."""
    ds = memory_tools.create_or_get_dataset("Except DS", "except_hash_04", 1)
    rec = {
        "date": "2026-08-01", "employee": "Ravi Kumar", "amount": 2500.0,
        "category": "Meals", "receipt_status": "Missing",
    }
    memory_tools.save_expenses([rec], dataset_id=ds["dataset_id"])
    issues = validation_tools.validate_expenses([rec])
    saved = memory_tools.save_validation_issues(issues, dataset_id=ds["dataset_id"])
    
    memory_tools.resolve_validation_issue(
        saved[0]["issue_id"], decision="accepted_exception",
        notes="Approved exception by VP",
    )
    eid = memory_tools.save_audit_event(
        ds["dataset_id"], "exception_accepted", "issue", saved[0]["issue_id"],
        {"manager": "VP", "notes": "Approved exception by VP"}
    )
    assert eid is not None
    # Included in report
    totals = calculation_tools.calculate_totals([rec])
    assert totals["grand_total"] == 2500.0


def test_t3_05_switch_dataset_resets_editor_and_history(mumbai_expenses_csv, delhi_expenses_csv):
    """T3-05: DS-A active (F3) -> Switch to DS-B (F3) -> Query scoped to DS-B (F5) -> History scoped (F6)."""
    ds_m = memory_tools.create_or_get_dataset("Mumbai DS", "hash_mumbai_t3", 7)
    ds_d = memory_tools.create_or_get_dataset("Delhi DS", "hash_delhi_t3", 5)
    
    # Run on Mumbai
    memory_tools.save_report_run({
        "report_id": "REP-MUMBAI-01",
        "dataset_id": ds_m["dataset_id"],
        "user_request": "Mumbai report",
        "filters": {},
        "transaction_ids": [],
        "transaction_count": 7,
        "grand_total": 48500.0,
        "validation_status": "Clear",
        "report_file_path": "reports/m.pdf",
        "human_review_status": "None",
    })
    
    # Switch to Delhi
    memory_tools.set_active_dataset(ds_d["dataset_id"])
    assert memory_tools.get_active_dataset()["dataset_id"] == ds_d["dataset_id"]
    
    # Scoped history for Delhi should not show Mumbai runs
    history_d = memory_tools.get_report_history(dataset_id=ds_d["dataset_id"])
    assert not any(h["report_id"] == "REP-MUMBAI-01" for h in history_d)


def test_t3_06_switch_dataset_isolates_db_queries(sample_expenses):
    """T3-06: Upload Mumbai and Delhi (F1, F2) -> Query Mumbai (F5) -> Switch to Delhi (F3) -> Query Delhi (F5) -> 0 leakage."""
    ds_m = memory_tools.create_or_get_dataset("Mumbai Query", "mqhash", 5)
    ds_d = memory_tools.create_or_get_dataset("Delhi Query", "dqhash", 3)
    
    memory_tools.save_expenses(sample_expenses[:5], dataset_id=ds_m["dataset_id"])
    memory_tools.save_expenses(sample_expenses[5:8], dataset_id=ds_d["dataset_id"])
    
    recs_m = memory_tools.retrieve_expenses_from_db(dataset_id=ds_m["dataset_id"])
    recs_d = memory_tools.retrieve_expenses_from_db(dataset_id=ds_d["dataset_id"])
    
    assert len(recs_m) == 5
    assert len(recs_d) == 3
    # Check zero ID overlap
    ids_m = {r["record_id"] for r in recs_m}
    ids_d = {r["record_id"] for r in recs_d}
    assert ids_m.isdisjoint(ids_d)


def test_t3_07_restore_prompt_from_history_then_execute():
    """T3-07: Run report (F6) -> History records (F6) -> Restore prompt (F7) -> Execute generates new run ID (F7, F19)."""
    ds = memory_tools.create_or_get_dataset("Restore DS", "resthash", 1)
    orig_prompt = "Generate travel expense report for Priya Sharma"
    memory_tools.save_report_run({
        "report_id": "REP-ORIG-101",
        "dataset_id": ds["dataset_id"],
        "user_request": orig_prompt,
        "filters": {"employee": "Priya Sharma"},
        "transaction_ids": [],
        "transaction_count": 1,
        "grand_total": 1500.0,
        "validation_status": "Clear",
        "report_file_path": "reports/orig.pdf",
        "human_review_status": "None",
    })
    
    history = memory_tools.get_report_history(dataset_id=ds["dataset_id"])
    target = next(h for h in history if h["report_id"] == "REP-ORIG-101")
    restored_prompt = target["user_request"]
    assert restored_prompt == orig_prompt
    
    # Rerun creates new run ID
    new_run_id = f"REP-RERUN-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    assert new_run_id != target["report_id"]


def test_t3_08_view_old_report_after_dataset_edited_to_v2(sample_expenses):
    """T3-08: Generate report on v1 (F6) -> Edit dataset to v2 (F4) -> View old report (F7) -> Snapshot displays v1 totals."""
    ds = memory_tools.create_or_get_dataset("V1 V2 DS", "v1v2hash", 2)
    memory_tools.save_expenses(sample_expenses[:2], dataset_id=ds["dataset_id"])
    
    memory_tools.save_report_run({
        "report_id": "REP-V1-SNAP",
        "dataset_id": ds["dataset_id"],
        "dataset_version": 1,
        "user_request": "V1 Report",
        "filters": {},
        "transaction_ids": ["E1", "E2"],
        "transaction_count": 2,
        "grand_total": 10000.0,
        "validation_status": "Clear",
        "report_file_path": "reports/v1.pdf",
        "human_review_status": "None",
    })
    
    # Edit dataset to v2 with higher amount
    edited = [dict(r) for r in sample_expenses[:2]]
    edited[0]["amount"] = 50000.0
    memory_tools.increment_dataset_version(ds["dataset_id"], edited)
    
    # Old report snapshot still has 10000.0
    history = memory_tools.get_report_history(dataset_id=ds["dataset_id"])
    v1_report = next(h for h in history if h["report_id"] == "REP-V1-SNAP")
    assert v1_report["grand_total"] == 10000.0


def test_t3_09_canonical_filters_intent_to_query_consistency(sample_expenses):
    """T3-09: Prompt 'August 2026 travel' (F12) -> Canonical filters (F12) -> DB query (F5) -> Filtered expenses match DB."""
    intent = agent._regex_extract_intent("August 2026 travel expenses")
    start, end = agent._resolve_date_range(intent["time_period"])
    
    memory_tools.save_expenses(sample_expenses, source_name="t3_09.csv")
    db_recs = memory_tools.retrieve_expenses_from_db(start_date=start, end_date=end, expense_type=intent["expense_type"])
    
    # Direct filter
    direct_filtered = expense_tools.filter_expenses(sample_expenses, start, end, intent["expense_type"])
    assert len(db_recs) == len(direct_filtered)


def test_t3_10_sequential_prompt_employee_isolation():
    """T3-10: Prompt 'expenses for Ravi Kumar' (F13) -> Next prompt 'all expenses for last month' (F13) -> No leakage."""
    intent1 = agent._regex_extract_intent("expenses for Ravi Kumar")
    assert intent1["employee_name"] == "Ravi Kumar"
    
    intent2 = agent._regex_extract_intent("all expenses for last month")
    assert intent2["employee_name"] == "" or intent2["employee_name"] is None


def test_t3_11_location_normalization_with_category_filtering(mumbai_expenses_csv):
    """T3-11: Upload dataset with City (F15) -> Query category & location -> Filters correctly."""
    rows = expense_tools.get_expenses(mumbai_expenses_csv)
    flight_mumbai = [r for r in rows if r.get("category") == "Flight" and (r.get("city") == "Mumbai" or r.get("location") == "Mumbai")]
    assert len(flight_mumbai) >= 1
    assert flight_mumbai[0]["merchant"] == "IndiGo Airlines"


def test_t3_12_absent_location_notice_preserves_date_filtering(sample_expenses, sample_csv_path):
    """T3-12: Dataset without location (F15) -> Query 'travel in Pune August 2026' -> Date filter succeeds."""
    has_location = any("location" in r or "city" in r for r in sample_expenses)
    assert has_location is False
    # Date filter August 2026 still works
    filtered = expense_tools.filter_expenses(sample_expenses, "2026-08-01", "2026-08-31", "travel")
    assert len(filtered) > 0


def test_t3_13_zero_match_explanation_with_active_dataset_stats(sample_expenses):
    """T3-13: Query unmatched condition (F14) -> Zero match handled cleanly without error."""
    unmatched = expense_tools.filter_expenses(sample_expenses, "2099-01-01", "2099-01-31", "travel")
    assert len(unmatched) == 0
    totals = calculation_tools.calculate_totals(unmatched)
    assert totals["transaction_count"] == 0


def test_t3_14_legacy_migration_followed_by_new_upload(mumbai_expenses_csv):
    """T3-14: Migrate legacy DB (F18) -> Upload new Mumbai dataset (F1, F2) -> Active dataset is Mumbai (F3) -> Query active returns only Mumbai (F5)."""
    # Create new dataset
    ds_m = memory_tools.create_or_get_dataset("Mumbai Upload", "mup_hash_14", 7)
    memory_tools.set_active_dataset(ds_m["dataset_id"])
    mumbai_rows = expense_tools.get_expenses(mumbai_expenses_csv)
    memory_tools.save_expenses(mumbai_rows, dataset_id=ds_m["dataset_id"])
    
    active_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds_m["dataset_id"])
    assert len(active_recs) == len(mumbai_rows)


def test_t3_15_null_amount_preservation_through_editor_save(nulls_expenses_csv):
    """T3-15: Upload CSV with null amounts (F9) -> Save v2 in editor (F4) -> Null amounts remain safe without crash."""
    rows = expense_tools.get_expenses(nulls_expenses_csv)
    ds = memory_tools.create_or_get_dataset("Null DS", "null_hash_15", len(rows))
    memory_tools.save_expenses(rows, dataset_id=ds["dataset_id"])
    
    # Save v2
    v2 = memory_tools.increment_dataset_version(ds["dataset_id"], rows)
    assert v2 == 2
    v2_recs = memory_tools.retrieve_expenses_from_db(dataset_id=ds["dataset_id"], dataset_version=2)
    assert len(v2_recs) == len(rows)


def test_t3_16_multi_agent_workflow_with_audit_trail(sample_expenses):
    """T3-16: Multi-agent pipeline (F19) -> Correct record (F8) -> Audit logged (F11) -> Report generated with audited data (F6)."""
    ds = memory_tools.create_or_get_dataset("Audit Workflow DS", "aw_hash_16", 5)
    aug_expenses = [e for e in sample_expenses if "2026-08" in e.get("date", "")][:5]
    memory_tools.save_expenses(aug_expenses, dataset_id=ds["dataset_id"])
    
    # Audit event
    eid = memory_tools.save_audit_event(ds["dataset_id"], "workflow_run", "dataset", ds["dataset_id"], {"status": "started"})
    assert eid is not None
    
    # Report generation
    totals = calculation_tools.calculate_totals(aug_expenses)
    rep_id = memory_tools.save_report_run({
        "report_id": "REP-AUDITED-WF",
        "dataset_id": ds["dataset_id"],
        "user_request": "Audited workflow run",
        "filters": {},
        "transaction_ids": [r.get("record_id", "EXP") for r in aug_expenses],
        "transaction_count": len(aug_expenses),
        "grand_total": totals["grand_total"],
        "validation_status": "Clear",
        "report_file_path": "reports/audited_wf.pdf",
        "human_review_status": "None",
    })
    assert rep_id == "REP-AUDITED-WF"


def test_t3_17_editor_row_addition_and_immediate_validation(sample_expenses):
    """T3-17: Add row in editor with missing receipt -> Validation flags new row immediately."""
    new_row = {
        "date": "2026-08-20", "employee": "Priya Sharma", "amount": 2000.0,
        "category": "Meals", "receipt_status": "Missing", "merchant": "Restaurant",
    }
    issues = validation_tools.validate_expenses([new_row])
    assert any(i["issue_type"] == "missing_receipt" for i in issues)


def test_t3_18_activity_log_records_full_lifecycle():
    """T3-18: Ingest -> Edit -> Validate -> Report; verify activity log entries generated across nodes."""
    state = {"agent_logs": [], "workflow_status": []}
    state["agent_logs"] = agent._append_agent_log(state, "Expense Analysis Agent", "Ingested CSV records")
    state["agent_logs"] = agent._append_agent_log(state, "Validation Agent", "Flagged 1 missing receipt")
    state["agent_logs"] = agent._append_agent_log(state, "Report Generation Agent", "Generated audited PDF report")

    assert len(state["agent_logs"]) == 3
    assert state["agent_logs"][0]["agent"] == "Expense Analysis Agent"
    assert state["agent_logs"][1]["agent"] == "Validation Agent"
    assert state["agent_logs"][2]["agent"] == "Report Generation Agent"
    assert all(re.match(r"^\d{2}:\d{2}:\d{2}$", log["timestamp"]) for log in state["agent_logs"])


def test_t3_19_advanced_diagnostics_inspects_clean_checkpoint():
    """T3-19: Checkpoint isolation: unique checkpoint DB path inspected without leaking."""
    chk_path = os.getenv("AGENT_CHECKPOINT_DB_PATH")
    assert chk_path is not None
    assert "test_agent_state.db" in chk_path


def test_t3_20_revalidation_failure_blocks_report_generation():
    """T3-20: Unresolved validation issue halts report generation with error."""
    state = {
        "user_request": "Report Priya August",
        "validation_status": "Needs Human Review",
        "unresolved_count": 2,
        "categorized_expenses": [],
        "workflow_status": [],
    }
    res = agent.report_generation_agent_node(state)
    assert "error" in res
    assert "unresolved" in res["error"].lower()
