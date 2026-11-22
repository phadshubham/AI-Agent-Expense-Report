"""
Milestone 3 Compliance & Validation Editing Workspace Test Suite.

Verifies:
- apply_reviewer_decision: "correct", "exclude", "accept_exception"
- 8-field editing through validation and memory pipeline
- Immediate issue resolution and audit event logging
- Dataset listing and metadata retrieval
- Isolated temporary SQLite database usage
"""

import pytest
from tools.memory_tools import (
    init_memory_db,
    create_or_get_dataset,
    set_active_dataset,
    save_expenses,
    save_validation_issues,
    get_unresolved_issues,
    get_expense_by_record_id,
    apply_reviewer_decision,
    get_audit_events,
    list_datasets,
    get_dataset,
)


class TestReviewerDecisionCorrect:
    """Test inline correction of flagged records via apply_reviewer_decision."""

    def test_correct_null_amount_and_receipt(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_m3.db")
        monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", test_db)
        init_memory_db(test_db)

        ds = create_or_get_dataset(
            name="M3 Test Ingestion",
            file_hash="hash-m3-01",
            row_count=1,
            db_path=test_db,
        )
        ds_id = ds["dataset_id"]

        raw_recs = [
            {
                "record_id": "REC-M3-001",
                "date": "2026-05-10",
                "employee": "Amit Patel",
                "description": "Client Dinner",
                "merchant": "Trishna",
                "category": "Meals",
                "amount": None,
                "receipt_status": "Missing",
            }
        ]
        save_expenses(raw_recs, dataset_id=ds_id, dataset_version=1, db_path=test_db)

        issues = [
            {
                "issue_id": "ISS-M3-001",
                "expense_record_id": "REC-M3-001",
                "issue_type": "invalid_amount",
                "field_name": "amount",
                "message": "Null or invalid amount",
                "severity": "high",
            },
            {
                "issue_id": "ISS-M3-002",
                "expense_record_id": "REC-M3-001",
                "issue_type": "missing_receipt",
                "field_name": "receipt_status",
                "message": "Missing receipt",
                "severity": "medium",
            },
        ]
        save_validation_issues(issues, dataset_id=ds_id, dataset_version=1, db_path=test_db)

        open_issues = get_unresolved_issues(dataset_id=ds_id, db_path=test_db)
        assert len(open_issues) == 2

        result = apply_reviewer_decision(
            action="correct",
            record_id="REC-M3-001",
            dataset_id=ds_id,
            dataset_version=1,
            changes={"amount": 2500.0, "receipt_status": "Verified"},
            reason="Provided receipt and corrected amount",
            db_path=test_db,
        )

        assert result["action"] == "correct"
        assert result["success"] is True
        assert len(result["remaining_issues"]) == 0
        assert result["audit_event_id"].startswith("AUD-")

        rec = get_expense_by_record_id("REC-M3-001", dataset_id=ds_id, db_path=test_db)
        assert rec is not None
        assert rec["amount"] == 2500.0
        assert rec["receipt_status"] == "Verified"

        remaining_unresolved = get_unresolved_issues(dataset_id=ds_id, db_path=test_db)
        assert len(remaining_unresolved) == 0

        events = get_audit_events(dataset_id=ds_id, entity_id="REC-M3-001", db_path=test_db)
        assert len(events) >= 1
        assert events[0]["event_type"] == "reviewer_correction"

    def test_eight_field_editing(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_m3_8f.db")
        monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", test_db)
        init_memory_db(test_db)

        ds = create_or_get_dataset(name="8-Field Test", file_hash="hash-8f", row_count=1, db_path=test_db)
        ds_id = ds["dataset_id"]

        save_expenses(
            [{
                "record_id": "REC-8F",
                "date": "2026-01-01",
                "employee": "Old Emp",
                "description": "Old Desc",
                "merchant": "Old Merch",
                "category": "Other",
                "amount": 10.0,
                "receipt_status": "Missing",
                "location": "Old Loc",
            }],
            dataset_id=ds_id,
            dataset_version=1,
            db_path=test_db,
        )

        # Update all 8 fields simultaneously
        changes = {
            "date": "2026-05-20",
            "employee": "Vikram Seth",
            "description": "Conference Pass",
            "merchant": "TechCon Global",
            "category": "Registration",
            "amount": 15000.0,
            "receipt_status": "Verified",
            "location": "Bengaluru",
        }
        res = apply_reviewer_decision(
            action="correct",
            record_id="REC-8F",
            dataset_id=ds_id,
            dataset_version=1,
            changes=changes,
            reason="Full record revision",
            db_path=test_db,
        )
        assert res["success"] is True

        rec = get_expense_by_record_id("REC-8F", dataset_id=ds_id, db_path=test_db)
        assert rec["date"] == "2026-05-20"
        assert rec["employee"] == "Vikram Seth"
        assert rec["description"] == "Conference Pass"
        assert rec["merchant"] == "TechCon Global"
        assert rec["category"] == "Registration"
        assert rec["amount"] == 15000.0
        assert rec["receipt_status"] == "Verified"
        assert rec["location"] == "Bengaluru"


class TestReviewerDecisionExclude:
    """Test excluding flagged records from counting and reports."""

    def test_exclude_record(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_m3_ex.db")
        monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", test_db)
        init_memory_db(test_db)

        ds = create_or_get_dataset(
            name="M3 Exclude Test",
            file_hash="hash-m3-02",
            row_count=1,
            db_path=test_db,
        )
        ds_id = ds["dataset_id"]

        raw_recs = [
            {
                "record_id": "REC-M3-002",
                "date": "2026-05-12",
                "employee": "Priya Sharma",
                "description": "Taxi",
                "merchant": "Uber",
                "category": "Transport",
                "amount": 450.0,
                "receipt_status": "Missing",
            }
        ]
        save_expenses(raw_recs, dataset_id=ds_id, dataset_version=1, db_path=test_db)

        issues = [
            {
                "issue_id": "ISS-M3-003",
                "expense_record_id": "REC-M3-002",
                "issue_type": "missing_receipt",
                "field_name": "receipt_status",
                "message": "Missing receipt",
                "severity": "medium",
            }
        ]
        save_validation_issues(issues, dataset_id=ds_id, dataset_version=1, db_path=test_db)

        result = apply_reviewer_decision(
            action="exclude",
            record_id="REC-M3-002",
            dataset_id=ds_id,
            dataset_version=1,
            reason="Personal trip, excluded from company reporting",
            db_path=test_db,
        )

        assert result["action"] == "exclude"
        assert result["success"] is True

        rec = get_expense_by_record_id("REC-M3-002", dataset_id=ds_id, db_path=test_db)
        assert rec["is_excluded"] == 1

        events = get_audit_events(dataset_id=ds_id, entity_id="REC-M3-002", db_path=test_db)
        assert len(events) >= 1
        assert events[0]["event_type"] == "reviewer_exclusion"


class TestReviewerDecisionAcceptException:
    """Test managerial exception authorization."""

    def test_accept_exception(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_m3_acc.db")
        monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", test_db)
        init_memory_db(test_db)

        ds = create_or_get_dataset(
            name="M3 Accept Test",
            file_hash="hash-m3-03",
            row_count=1,
            db_path=test_db,
        )
        ds_id = ds["dataset_id"]

        raw_recs = [
            {
                "record_id": "REC-M3-003",
                "date": "2026-05-15",
                "employee": "Ravi Kumar",
                "description": "Hotel Incidentals",
                "merchant": "Taj",
                "category": "Accommodation",
                "amount": 800.0,
                "receipt_status": "Missing",
            }
        ]
        save_expenses(raw_recs, dataset_id=ds_id, dataset_version=1, db_path=test_db)

        issues = [
            {
                "issue_id": "ISS-M3-004",
                "expense_record_id": "REC-M3-003",
                "issue_type": "missing_receipt",
                "field_name": "receipt_status",
                "message": "Missing receipt",
                "severity": "medium",
            }
        ]
        save_validation_issues(issues, dataset_id=ds_id, dataset_version=1, db_path=test_db)

        result = apply_reviewer_decision(
            action="accept_exception",
            record_id="REC-M3-003",
            dataset_id=ds_id,
            dataset_version=1,
            reason="Authorized exception approved by Finance Director",
            db_path=test_db,
        )

        assert result["action"] == "accept_exception"
        assert result["success"] is True

        open_issues = get_unresolved_issues(dataset_id=ds_id, db_path=test_db)
        assert len(open_issues) == 0

        events = get_audit_events(dataset_id=ds_id, entity_id="REC-M3-003", db_path=test_db)
        assert len(events) >= 1
        assert events[0]["event_type"] == "reviewer_exception_accepted"


class TestDatasetListingAndMetadata:
    """Test dataset discovery APIs."""

    def test_list_and_get_dataset(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_m3_ds.db")
        monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", test_db)
        init_memory_db(test_db)

        ds1 = create_or_get_dataset(name="Dataset One", file_hash="hash-1", row_count=50, db_path=test_db)
        ds2 = create_or_get_dataset(name="Dataset Two", file_hash="hash-2", row_count=100, db_path=test_db)

        all_ds = list_datasets(db_path=test_db)
        assert len(all_ds) >= 2
        assert all_ds[0]["dataset_id"] == ds2["dataset_id"]
        assert all_ds[0]["is_active"] == 1

        fetched = get_dataset(ds1["dataset_id"], db_path=test_db)
        assert fetched is not None
        assert fetched["name"] == "Dataset One"
        assert fetched["row_count"] == 50


class TestInvalidReviewerAction:
    """Test validation of unknown actions."""

    def test_unknown_action_raises(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_m3_inv.db")
        monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", test_db)
        init_memory_db(test_db)

        with pytest.raises(ValueError, match="Unknown reviewer action"):
            apply_reviewer_decision(
                action="invalid_action",
                record_id="REC-999",
                db_path=test_db,
            )


class TestWorkflowRemembersAuditorDecisions:
    """
    Verifies that auditor decisions made in Tab 4 / persistent memory:
    - Are remembered across workflow executions.
    - When all flagged transactions are pre-authorized (accept_exception) or excluded (exclude),
      the workflow DOES NOT pause for human review and proceeds directly to Report Generation.
    - Zero silent approvals: if there are any un-audited/unresolved issues, workflow MUST interrupt.
    """

    def test_preauthorized_managerial_exception_bypasses_interrupt(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_m3_hitl_bypass.db")
        checkpoint_db = str(tmp_path / "test_checkpoints.db")
        monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", test_db)
        monkeypatch.setenv("AGENT_CHECKPOINT_DB_PATH", checkpoint_db)
        init_memory_db(test_db)

        ds = create_or_get_dataset(name="HITL Bypass Test", file_hash="hash-hitl-01", row_count=1, db_path=test_db)
        ds_id = ds["dataset_id"]
        set_active_dataset(ds_id, db_path=test_db)

        raw_recs = [
            {
                "record_id": "EXP-PRE-AUTH-01",
                "date": "2026-08-28",
                "employee": "Priya Sharma",
                "description": "Hotel to Meeting Cab",
                "merchant": "BluSmart",
                "category": "Transport",
                "amount": 350.0,
                "receipt_status": "Missing",
                "location": "Mumbai",
            }
        ]
        save_expenses(raw_recs, dataset_id=ds_id, dataset_version=1, db_path=test_db)

        issues = [
            {
                "issue_id": "ISS-PRE-AUTH-01",
                "expense_record_id": "EXP-PRE-AUTH-01",
                "issue_type": "missing_receipt",
                "field_name": "receipt_status",
                "message": "Missing receipt for 'Hotel to Meeting Cab' - 350.00",
                "severity": "medium",
            }
        ]
        save_validation_issues(issues, dataset_id=ds_id, dataset_version=1, db_path=test_db)

        # Auditor direct resolution: authorize managerial exception
        apply_reviewer_decision(
            action="accept_exception",
            record_id="EXP-PRE-AUTH-01",
            dataset_id=ds_id,
            dataset_version=1,
            reason="Pre-authorized managerial exception by CFO",
            db_path=test_db,
        )

        from agent import get_compiled_graph
        graph, _ = get_compiled_graph()
        import uuid
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        initial_state = {
            "user_request": "Travel expenses for Priya Sharma in August 2026",
            "dataset_id": ds_id,
            "dataset_version": 1,
            "expenses": raw_recs,
        }

        result = None
        for event in graph.stream(initial_state, config, stream_mode="values"):
            result = event

        state = graph.get_state(config)
        assert len(state.tasks) == 0, "Workflow should NOT have interrupted because exception was pre-authorized!"
        assert result is not None
        assert result.get("validation_status") == "Reviewed with Exceptions"
        assert result.get("pdf_path") is not None
        assert result.get("totals", {}).get("grand_total") == 350.0
        assert len(result.get("human_decisions", [])) >= 1
        assert result.get("human_decisions")[0]["action"] == "accepted_exception"

    def test_preauthorized_exclusion_bypasses_interrupt(self, tmp_path, monkeypatch):
        test_db = str(tmp_path / "test_m3_hitl_ex_bypass.db")
        checkpoint_db = str(tmp_path / "test_checkpoints_ex.db")
        monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", test_db)
        monkeypatch.setenv("AGENT_CHECKPOINT_DB_PATH", checkpoint_db)
        init_memory_db(test_db)

        ds = create_or_get_dataset(name="HITL Exclude Bypass Test", file_hash="hash-hitl-02", row_count=2, db_path=test_db)
        ds_id = ds["dataset_id"]
        set_active_dataset(ds_id, db_path=test_db)

        raw_recs = [
            {
                "record_id": "EXP-VALID-01",
                "date": "2026-08-15",
                "employee": "Priya Sharma",
                "description": "Valid Lunch",
                "merchant": "Subway",
                "category": "Meals",
                "amount": 200.0,
                "receipt_status": "Verified",
                "location": "Mumbai",
            },
            {
                "record_id": "EXP-FLAGGED-02",
                "date": "2026-08-20",
                "employee": "Priya Sharma",
                "description": "Taxi without receipt",
                "merchant": "Ola",
                "category": "Transport",
                "amount": 500.0,
                "receipt_status": "Missing",
                "location": "Mumbai",
            },
        ]
        save_expenses(raw_recs, dataset_id=ds_id, dataset_version=1, db_path=test_db)

        issues = [
            {
                "issue_id": "ISS-FLAGGED-02",
                "expense_record_id": "EXP-FLAGGED-02",
                "issue_type": "missing_receipt",
                "field_name": "receipt_status",
                "message": "Missing receipt for Taxi",
                "severity": "medium",
            }
        ]
        save_validation_issues(issues, dataset_id=ds_id, dataset_version=1, db_path=test_db)

        # Auditor excludes the flagged record
        apply_reviewer_decision(
            action="exclude",
            record_id="EXP-FLAGGED-02",
            dataset_id=ds_id,
            dataset_version=1,
            reason="Personal trip excluded from reporting",
            db_path=test_db,
        )

        from agent import get_compiled_graph
        graph, _ = get_compiled_graph()
        import uuid
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        initial_state = {
            "user_request": "All expenses for Priya Sharma in August 2026",
            "dataset_id": ds_id,
            "dataset_version": 1,
            "expenses": raw_recs,
        }

        result = None
        for event in graph.stream(initial_state, config, stream_mode="values"):
            result = event

        state = graph.get_state(config)
        assert len(state.tasks) == 0, "Workflow should NOT have interrupted because flagged item was pre-excluded!"
        assert result is not None
        assert result.get("validation_status") == "Clear"
        # Only the valid 200.0 meal should be counted, 500.0 taxi is excluded!
        assert result.get("totals", {}).get("grand_total") == 200.0
        assert result.get("totals", {}).get("transaction_count") == 1
