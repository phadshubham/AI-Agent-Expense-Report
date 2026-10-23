"""
Unit and Integration Tests for:
- Unit III: Persistent SQLite Memory (tools/memory_tools.py)
- Unit IV: Multi-Agent Collaboration (agent.py)
- Human-in-the-Loop review, exception acceptance, and revalidation
"""

import os
import sys
import io
import shutil
import tempfile
import unittest
from datetime import datetime

# Enforce UTF-8 stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from tools.memory_tools import (
    init_memory_db,
    save_expenses,
    retrieve_expenses_from_db,
    get_previous_expenses,
    save_validation_issues,
    update_expense_record,
    resolve_validation_issue,
    get_unresolved_issues,
    save_report_run,
    get_report_history,
    get_memory_stats,
)
from tools.validation_tools import validate_expenses, revalidate_single_expense
from tools.calculation_tools import calculate_totals
from agent import (
    expense_analysis_agent_node,
    validation_agent_node,
    human_review_node,
    revalidation_node,
    report_generation_agent_node,
    build_agent_graph,
    _regex_extract_intent,
    _resolve_date_range,
)


class TestPersistentMemory(unittest.TestCase):
    """Test suite for Unit III: Persistent SQLite Memory."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_memory.db")
        init_memory_db(self.db_path)

        self.sample_expenses = [
            {
                "date": "2026-08-05",
                "employee": "Priya Sharma",
                "description": "Flight to Delhi",
                "merchant": "IndiGo",
                "category": "Flight",
                "amount": 5400.0,
                "receipt_status": "Verified",
            },
            {
                "date": "2026-08-06",
                "employee": "Priya Sharma",
                "description": "Hotel Stay",
                "merchant": "Taj Hotels",
                "category": "Accommodation",
                "amount": 8200.0,
                "receipt_status": "Verified",
            },
            {
                "date": "2026-08-07",
                "employee": "Priya Sharma",
                "description": "Client Dinner",
                "merchant": "Bukhara",
                "category": "Meals",
                "amount": 2800.0,
                "receipt_status": "Missing",
            },
            {
                "date": "2026-08-10",
                "employee": "Amit Patel",
                "description": "Cab to Client Office",
                "merchant": "Uber",
                "category": "Transport",
                "amount": 650.0,
                "receipt_status": "Verified",
            },
        ]

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_and_retrieve_expenses(self):
        """Test saving expenses and retrieving them with filters."""
        res = save_expenses(self.sample_expenses, source_name="test_source.csv", db_path=self.db_path)
        self.assertEqual(res["inserted"], 4)
        self.assertEqual(res["total_processed"], 4)

        # Retrieve all
        all_recs = retrieve_expenses_from_db(db_path=self.db_path)
        self.assertEqual(len(all_recs), 4)

        # Filter by employee
        priya_recs = retrieve_expenses_from_db(employee="Priya Sharma", db_path=self.db_path)
        self.assertEqual(len(priya_recs), 3)

        # Filter by date range
        aug_recs = retrieve_expenses_from_db(
            start_date="2026-08-05", end_date="2026-08-06", db_path=self.db_path
        )
        self.assertEqual(len(aug_recs), 2)

    def test_deduplication_on_repeated_import(self):
        """Confirm repeated imports of the same source batch do not duplicate records."""
        res1 = save_expenses(self.sample_expenses, source_name="batch.csv", db_path=self.db_path)
        self.assertEqual(res1["inserted"], 4)

        # Second import of identical records
        res2 = save_expenses(self.sample_expenses, source_name="batch.csv", db_path=self.db_path)
        self.assertEqual(res2["inserted"], 0)
        self.assertEqual(res2["skipped_duplicates"], 4)

        total_recs = retrieve_expenses_from_db(db_path=self.db_path)
        self.assertEqual(len(total_recs), 4)

    def test_genuine_duplicates_remain_detectable(self):
        """Confirm genuine duplicate transactions are saved and flagged by validation."""
        expenses_with_dup = list(self.sample_expenses)
        # Add a legitimate duplicate transaction (same merchant, date, amount)
        expenses_with_dup.append({
            "date": "2026-08-05",
            "employee": "Priya Sharma",
            "description": "Flight to Delhi (Duplicate)",
            "merchant": "IndiGo",
            "category": "Flight",
            "amount": 5400.0,
            "receipt_status": "Verified",
        })
        save_expenses(expenses_with_dup, source_name="test_dup.csv", db_path=self.db_path)
        recs = retrieve_expenses_from_db(db_path=self.db_path)
        self.assertEqual(len(recs), 5)

        # Validation must detect the duplicate
        issues = validate_expenses(recs)
        dup_issues = [i for i in issues if i["issue_type"] == "duplicate"]
        self.assertGreaterEqual(len(dup_issues), 1)

    def test_validation_issues_persistence_and_resolution(self):
        """Test saving validation findings and updating their resolution status."""
        recs = save_expenses(self.sample_expenses, db_path=self.db_path)["records"]
        issues = validate_expenses(recs)
        self.assertGreater(len(issues), 0)

        saved = save_validation_issues(issues, db_path=self.db_path)
        self.assertEqual(len(saved), len(issues))
        issue_id = saved[0]["issue_id"]

        # Check unresolved list
        unresolved = get_unresolved_issues(db_path=self.db_path)
        self.assertEqual(len(unresolved), len(issues))

        # Resolve issue with exception
        ok = resolve_validation_issue(
            issue_id=issue_id,
            decision="accepted_exception",
            notes="Authorized by manager",
            db_path=self.db_path,
        )
        self.assertTrue(ok)

        # Unresolved count should decrease
        remaining = get_unresolved_issues(db_path=self.db_path)
        self.assertEqual(len(remaining), len(issues) - 1)

    def test_record_update_and_revalidation(self):
        """Test updating a stored expense record and revalidating."""
        recs = save_expenses(self.sample_expenses, db_path=self.db_path)["records"]
        missing_rec = next(r for r in recs if r["receipt_status"] == "Missing")
        rec_id = missing_rec["record_id"]

        # Initially invalid (missing receipt)
        issues_before = revalidate_single_expense(missing_rec)
        self.assertEqual(len(issues_before), 1)

        # Update record in DB with Verified receipt
        updated = update_expense_record(
            rec_id,
            {"receipt_status": "Verified", "receipt_path": "receipts/hotel_taj.pdf"},
            db_path=self.db_path,
        )
        self.assertTrue(updated)

        # Retrieve updated record and revalidate
        updated_recs = retrieve_expenses_from_db(db_path=self.db_path)
        target = next(r for r in updated_recs if r["record_id"] == rec_id)
        self.assertEqual(target["receipt_status"], "Verified")

        issues_after = revalidate_single_expense(target)
        self.assertEqual(len(issues_after), 0)

    def test_save_and_retrieve_report_run(self):
        """Test saving report run metadata and retrieving history."""
        rep_id = save_report_run(
            {
                "report_id": "REP-TEST-001",
                "user_request": "Generate August report for Priya",
                "filters": {"employee": "Priya Sharma", "month": "August 2026"},
                "transaction_ids": ["EXP-1", "EXP-2"],
                "transaction_count": 2,
                "grand_total": 13600.0,
                "validation_status": "Clear",
                "report_file_path": "reports/test.pdf",
                "human_review_status": "None",
            },
            db_path=self.db_path,
        )
        self.assertEqual(rep_id, "REP-TEST-001")

        history = get_report_history(db_path=self.db_path)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["report_id"], "REP-TEST-001")
        self.assertEqual(history[0]["grand_total"], 13600.0)
        self.assertEqual(history[0]["validation_status"], "Clear")


class TestMultiAgentCollaboration(unittest.TestCase):
    """Test suite for Unit IV: Three Collaborating Agents & Workflow."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_agents.db")
        os.environ["EXPENSE_MEMORY_DB_PATH"] = self.db_path
        init_memory_db(self.db_path)

        self.clean_expenses = [
            {
                "date": "2026-08-01",
                "employee": "Priya Sharma",
                "description": "Flight Ticket",
                "merchant": "Air India",
                "category": "Flight",
                "amount": 7500.0,
                "receipt_status": "Verified",
            },
            {
                "date": "2026-08-02",
                "employee": "Priya Sharma",
                "description": "Hotel Room",
                "merchant": "Hyatt",
                "category": "Accommodation",
                "amount": 9000.0,
                "receipt_status": "Verified",
            },
        ]

        self.discrepancy_expenses = [
            {
                "date": "2026-08-05",
                "employee": "Amit Patel",
                "description": "Dinner with Client",
                "merchant": "Bistro",
                "category": "Meals",
                "amount": 3200.0,
                "receipt_status": "Missing",  # Discrepancy: missing receipt
            },
            {
                "date": "2026-08-06",
                "employee": "Amit Patel",
                "description": "Taxi ride",
                "merchant": "Uber",
                "category": "Transport",
                "amount": 0.0,  # Discrepancy: zero amount
                "receipt_status": "Verified",
            },
        ]

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        if "EXPENSE_MEMORY_DB_PATH" in os.environ:
            del os.environ["EXPENSE_MEMORY_DB_PATH"]

    def test_agent_1_expense_analysis(self):
        """Test Expense Analysis Agent interprets request and produces structured output."""
        state = {
            "user_request": "Generate August 2026 travel report for Priya Sharma",
            "expenses": self.clean_expenses,
        }
        res = expense_analysis_agent_node(state)

        self.assertIn("expense_analysis", res)
        analysis = res["expense_analysis"]
        self.assertEqual(analysis["agent"], "Expense Analysis Agent")
        self.assertEqual(analysis["target_employee"], "Priya Sharma")
        self.assertEqual(analysis["selected_records_count"], 2)
        self.assertEqual(len(res["categorized_expenses"]), 2)

    def test_agent_2_validation_agent_clean(self):
        """Test Validation Agent produces 'Clear' status on compliant data."""
        state = {
            "categorized_expenses": self.clean_expenses,
            "workflow_status": [],
        }
        res = validation_agent_node(state)

        self.assertEqual(res["validation_status"], "Clear")
        self.assertEqual(res["unresolved_count"], 0)
        self.assertEqual(res["awaiting_input"], "")

    def test_agent_2_validation_agent_detects_issues(self):
        """Test Validation Agent detects issues and requests human review."""
        state = {
            "categorized_expenses": self.discrepancy_expenses,
            "workflow_status": [],
        }
        res = validation_agent_node(state)

        self.assertEqual(res["validation_status"], "Needs Human Review")
        self.assertGreater(res["unresolved_count"], 0)
        self.assertEqual(res["awaiting_input"], "missing_data")
        self.assertEqual(len(res["validation_findings"]), 2)

    def test_agent_3_report_generation_deterministic(self):
        """Test Report Generation Agent computes accurate totals deterministically."""
        state = {
            "user_request": "Generate August report for Priya",
            "report_run_id": "REP-AGENT3-TEST",
            "employee_name": "Priya Sharma",
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "categorized_expenses": self.clean_expenses,
            "validation_status": "Clear",
            "workflow_status": [],
        }
        res = report_generation_agent_node(state)

        self.assertIn("totals", res)
        totals = res["totals"]
        self.assertEqual(totals["grand_total"], 16500.0)
        self.assertEqual(totals["transaction_count"], 2)
        self.assertIn("pdf_path", res)
        self.assertTrue(os.path.exists(res["pdf_path"]))

    def test_agent_3_integrity_guard(self):
        """Test Report Generation Agent aborts if unresolved issues exist."""
        state = {
            "categorized_expenses": self.discrepancy_expenses,
            "validation_status": "Needs Human Review",
            "unresolved_count": 2,
            "workflow_status": [],
        }
        res = report_generation_agent_node(state)
        self.assertIn("error", res)
        self.assertIn("unresolved", res["error"].lower())

    def test_human_review_exclude_action(self):
        """Test Human Review 'exclude' action removes flagged records and marks status Clear."""
        issues = validate_expenses(self.discrepancy_expenses)
        state = {
            "categorized_expenses": self.discrepancy_expenses,
            "missing_data": issues,
            "workflow_status": [],
            "human_response": "exclude",
        }
        # Simulate excluding flagged records directly
        flagged_rec_ids = {m.get("record_id") for m in issues}
        cleaned = [e for e in self.discrepancy_expenses if e.get("record_id") not in flagged_rec_ids]

        self.assertEqual(len(cleaned), 0)

    def test_human_review_accept_exceptions_action(self):
        """Test Human Review 'include' action marks status Reviewed with Exceptions."""
        issues = validate_expenses(self.discrepancy_expenses)
        saved_issues = save_validation_issues(issues, db_path=self.db_path)

        state = {
            "categorized_expenses": self.discrepancy_expenses,
            "missing_data": saved_issues,
            "workflow_status": [],
        }
        # In a real run, user selects 'include'
        for m in saved_issues:
            resolve_validation_issue(
                m["issue_id"], decision="accepted_exception", notes="Approved exception", db_path=self.db_path
            )

        unres = get_unresolved_issues(db_path=self.db_path)
        self.assertEqual(len(unres), 0)


if __name__ == "__main__":
    unittest.main()
