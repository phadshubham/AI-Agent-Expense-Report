"""
Automated Test Suite for Milestone 2: Canonical Filter Pipeline & State Consistency.

Test Categories:
1. TestRegressionSequence:
   - "all expenses for last month" -> "all expenses for Ravi Kumar" -> "all expenses for last month"
   - Verifies employee is strictly None on 3rd prompt (zero state leakage).
   - Verifies node execution cleans prior run's employee state.
2. TestAllExpensesIntent:
   - "all expenses", "all employees", "all travel expenses", "all expenses for all employees", "everyone"
   - Asserts parsed_filters["employee"] is strictly None.
3. TestSubstringCollisionResistance:
   - Word-boundary matching preventing collisions with "May" (month), "will", "bill", "mark", "standard", "everyone".
   - Disambiguation of attribution and possessives.
4. TestZeroMatchExplanation:
   - Diagnostic breakdown for date range mismatch (noting min/max dataset dates).
   - Diagnostic breakdown for nonexistent employee (listing available employees).
   - Diagnostic breakdown for category / travel category mismatch.
   - Diagnostic breakdown for unsupported vs supported location mismatch.
   - Node execution setting filter_match_count=0 and zero_match_explanation.
5. TestLocationSchemaNormalization:
   - Mumbai dataset with 'city' normalizes to 'location', location_supported=True.
   - Delhi dataset with 'destination' normalizes to 'location', location_supported=True.
   - Absent location dataset flags location_supported=False without data fabrication.
   - retrieve_expenses_from_db graceful location bypass when location unsupported.
   - dataset_has_location_support helper validation.
6. TestCanonicalParsedFiltersPropagation:
   - ParsedFilters serialization roundtrip.
   - filter_expenses accepts canonical filters dict.
   - retrieve_expenses_from_db accepts canonical filters dict.
   - save_report_run and get_report_history persist canonical filters.
   - LangGraph node propagation across analysis, validation, and report generation.
"""

import os
import shutil
import tempfile
import json
import unittest
from datetime import datetime, timezone
from typing import List, Dict, Any

from state import AgentState, ParsedFilters
from tools.expense_tools import filter_expenses, normalize_expense_columns
from tools.memory_tools import (
    init_memory_db,
    create_or_get_dataset,
    set_active_dataset,
    save_expenses,
    retrieve_expenses_from_db,
    dataset_has_location_support,
    save_report_run,
    get_report_history,
)
from agent import (
    extract_canonical_filters,
    _regex_extract_intent,
    explain_zero_match,
    expense_analysis_agent_node,
    validation_agent_node,
    report_generation_agent_node,
)


class BaseMilestone2TestCase(unittest.TestCase):
    """Base test case setting up an isolated temporary SQLite database."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="m2_test_")
        self.db_path = os.path.join(self.temp_dir, "test_expense_memory.db")
        self.orig_env = os.environ.get("EXPENSE_MEMORY_DB_PATH")
        os.environ["EXPENSE_MEMORY_DB_PATH"] = self.db_path
        init_memory_db(self.db_path)

        # Create active test dataset
        self.dataset = create_or_get_dataset(
            name="M2_Test_Dataset",
            file_hash="hash_m2_test_abc123",
            row_count=5,
            schema={"columns": ["date", "employee", "category", "amount", "location"]},
            db_path=self.db_path,
        )
        self.dataset_id = self.dataset["dataset_id"]
        set_active_dataset(self.dataset_id, db_path=self.db_path)

        # Sample expenses with diverse employees, categories, and dates in August 2026
        self.sample_expenses = [
            {
                "date": "2026-08-05",
                "employee": "Ravi Kumar",
                "category": "Flight",
                "merchant": "Air India",
                "amount": 5400.0,
                "receipt_status": "Valid",
                "location": "Mumbai",
            },
            {
                "date": "2026-08-10",
                "employee": "Priya Sharma",
                "category": "Meals",
                "merchant": "Trishna Mumbai",
                "amount": 1250.0,
                "receipt_status": "Valid",
                "location": "Mumbai",
            },
            {
                "date": "2026-08-15",
                "employee": "Amit Patel",
                "category": "Transport",
                "merchant": "Uber Mumbai",
                "amount": 620.0,
                "receipt_status": "Valid",
                "location": "Mumbai",
            },
            {
                "date": "2026-08-20",
                "employee": "Ravi Kumar",
                "category": "Accommodation",
                "merchant": "Taj Mumbai",
                "amount": 8900.0,
                "receipt_status": "Valid",
                "location": "Mumbai",
            },
            {
                "date": "2026-08-25",
                "employee": "Sneha Reddy",
                "category": "Supplies",
                "merchant": "Office Depot",
                "amount": 450.0,
                "receipt_status": "Valid",
                "location": "Mumbai",
            },
        ]
        save_res = save_expenses(
            self.sample_expenses,
            dataset_id=self.dataset_id,
            dataset_version=1,
            source_name="m2_sample.csv",
            db_path=self.db_path,
        )
        self.saved_records = save_res["records"]

    def tearDown(self):
        if self.orig_env is not None:
            os.environ["EXPENSE_MEMORY_DB_PATH"] = self.orig_env
        else:
            os.environ.pop("EXPENSE_MEMORY_DB_PATH", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class TestRegressionSequence(BaseMilestone2TestCase):
    """
    R4 Regression test sequence:
    'all expenses for last month' -> 'all expenses for Ravi Kumar' -> 'all expenses for last month'
    Asserts employee is strictly None on 3rd turn without state leakage.
    """

    def test_r4_regression_three_turn_prompt_sequence(self):
        dataset_employees = ["Ravi Kumar", "Priya Sharma", "Amit Patel", "Sneha Reddy"]

        # Turn 1: "all expenses for last month"
        f1 = extract_canonical_filters("all expenses for last month", dataset_employees=dataset_employees)
        self.assertIsNone(f1["employee"], "Turn 1: employee must be None for 'all expenses for last month'")
        self.assertEqual(f1["expense_type"], "all")
        self.assertEqual(f1["time_period_label"], "last month")

        # Turn 2: "all expenses for Ravi Kumar"
        f2 = extract_canonical_filters("all expenses for Ravi Kumar", dataset_employees=dataset_employees)
        self.assertEqual(f2["employee"], "Ravi Kumar", "Turn 2: employee must be identified as 'Ravi Kumar'")
        self.assertEqual(f2["expense_type"], "all")

        # Turn 3: "all expenses for last month"
        f3 = extract_canonical_filters("all expenses for last month", dataset_employees=dataset_employees)
        self.assertIsNone(f3["employee"], "Turn 3: employee must strictly return None, with zero state leakage")
        self.assertEqual(f3["expense_type"], "all")

    def test_r4_regression_node_execution_cleans_employee_filter(self):
        """
        Verify that expense_analysis_agent_node clears prior employee filter from state
        when the new prompt requests 'all expenses for August 2026'.
        """
        # Simulate state preserved from a prior run for Ravi Kumar
        stale_state: AgentState = {
            "user_request": "all expenses for August 2026",
            "employee_name": "Ravi Kumar",
            "target_employee": "Ravi Kumar",
            "dataset_id": self.dataset_id,
            "dataset_version": 1,
            "expenses": self.saved_records,
            "workflow_status": [],
        }

        output = expense_analysis_agent_node(stale_state)

        # Asserts:
        self.assertIsNone(output.get("target_employee"), "target_employee must be None")
        self.assertIsNotNone(output.get("parsed_filters"))
        self.assertIsNone(output["parsed_filters"].get("employee"), "parsed_filters['employee'] must be None")

        # Multi-person analysis: all matching employees should be included
        categorized = output.get("categorized_expenses", [])
        employees_in_output = {e.get("employee") for e in categorized}
        self.assertIn("Ravi Kumar", employees_in_output)
        self.assertIn("Priya Sharma", employees_in_output)
        self.assertIn("Amit Patel", employees_in_output)
        self.assertEqual(output.get("employee_name"), "Company Team")

    def test_sequential_node_runs_prevent_leakage(self):
        """Sequential run of Turn 2 state followed by Turn 3 prompt."""
        # Turn 2 run
        state_turn2: AgentState = {
            "user_request": "all expenses for Ravi Kumar August 2026",
            "dataset_id": self.dataset_id,
            "dataset_version": 1,
            "expenses": self.saved_records,
            "workflow_status": [],
        }
        out_turn2 = expense_analysis_agent_node(state_turn2)
        self.assertEqual(out_turn2["target_employee"], "Ravi Kumar")
        self.assertEqual(out_turn2["employee_name"], "Ravi Kumar")

        # Turn 3 run passing prior state with Ravi Kumar
        state_turn3: AgentState = dict(out_turn2)
        state_turn3["user_request"] = "all expenses for August 2026"
        out_turn3 = expense_analysis_agent_node(state_turn3)

        self.assertIsNone(out_turn3["target_employee"])
        self.assertIsNone(out_turn3["parsed_filters"]["employee"])
        self.assertEqual(out_turn3["employee_name"], "Company Team")


class TestAllExpensesIntent(unittest.TestCase):
    """
    R4 Intent parsing tests:
    Deterministic interpretation of 'all expenses' and 'all employees' requests.
    """

    def test_all_expenses_explicit_none(self):
        f = extract_canonical_filters("all expenses")
        self.assertIsNone(f["employee"])
        self.assertEqual(f["expense_type"], "all")

    def test_all_employees_explicit_none(self):
        f = extract_canonical_filters("all employees travel for August")
        self.assertIsNone(f["employee"])
        self.assertEqual(f["expense_type"], "travel")

    def test_all_expenses_for_all_employees_explicit_none(self):
        f = extract_canonical_filters("all expenses for all employees")
        self.assertIsNone(f["employee"])
        self.assertEqual(f["expense_type"], "all")

    def test_show_all_employee_expenses_explicit_none(self):
        f = extract_canonical_filters("show all employee expenses")
        self.assertIsNone(f["employee"])

    def test_all_travel_expenses_explicit_none(self):
        f = extract_canonical_filters("all travel expenses for last month")
        self.assertIsNone(f["employee"])
        self.assertEqual(f["expense_type"], "travel")

    def test_everyone_and_company_wide_explicit_none(self):
        f1 = extract_canonical_filters("expenses for everyone")
        self.assertIsNone(f1["employee"])

        f2 = extract_canonical_filters("company-wide expenses for August")
        self.assertIsNone(f2["employee"])

        f3 = extract_canonical_filters("travel expenses across all team")
        self.assertIsNone(f3["employee"])

    def test_backward_compatible_regex_extract_intent(self):
        res1 = _regex_extract_intent("all expenses for last month")
        self.assertEqual(res1["employee_name"], "")
        self.assertEqual(res1["expense_type"], "all")
        self.assertEqual(res1["time_period"], "last month")

        res2 = _regex_extract_intent("expenses for Ravi Kumar")
        self.assertEqual(res2["employee_name"], "Ravi Kumar")
        self.assertEqual(res2["expense_type"], "travel")


class TestSubstringCollisionResistance(unittest.TestCase):
    """
    R4 Dynamic employee discovery collision tests:
    Guarantees common words ('will', 'May', 'standard', 'everyone', 'bill', 'mark')
    do not trigger false-positive employee matches.
    """

    def setUp(self):
        self.employees = [
            "May Brown",
            "Will Smith",
            "Dan Jones",
            "Eve Adams",
            "Bill Gates",
            "Mark Davis",
            "Priya Sharma",
            "Ravi Kumar",
        ]

    def test_month_may_does_not_match_employee_may(self):
        f = extract_canonical_filters("travel expenses for May 2026", dataset_employees=self.employees)
        self.assertIsNone(f["employee"], "Prompt 'travel expenses for May 2026' must not match employee 'May Brown'")
        self.assertEqual(f["time_period_label"], "may 2026")

    def test_modal_verb_will_does_not_match_employee_will(self):
        f = extract_canonical_filters("I will need all travel expenses", dataset_employees=self.employees)
        self.assertIsNone(f["employee"], "Word 'will' must not match employee 'Will Smith'")

    def test_word_standard_does_not_match_employee_dan(self):
        f = extract_canonical_filters("standard travel expenses", dataset_employees=self.employees)
        self.assertIsNone(f["employee"], "Word 'standard' must not match employee 'Dan Jones'")

    def test_word_everyone_does_not_match_employee_eve(self):
        f = extract_canonical_filters("all expenses for everyone", dataset_employees=self.employees)
        self.assertIsNone(f["employee"], "Word 'everyone' must not match employee 'Eve Adams'")

    def test_bill_does_not_match_employee_bill(self):
        f = extract_canonical_filters("show bill for August", dataset_employees=self.employees)
        self.assertIsNone(f["employee"], "Word 'bill' must not match employee 'Bill Gates'")

    def test_mark_does_not_match_employee_mark(self):
        f = extract_canonical_filters("mark expenses for August", dataset_employees=self.employees)
        self.assertIsNone(f["employee"], "Word 'mark' must not match employee 'Mark Davis'")

    def test_exact_employee_name_match(self):
        f = extract_canonical_filters("expenses for Priya Sharma", dataset_employees=self.employees)
        self.assertEqual(f["employee"], "Priya Sharma")

    def test_first_name_whole_word_boundary(self):
        f = extract_canonical_filters("expenses for Priya", dataset_employees=self.employees)
        self.assertEqual(f["employee"], "Priya Sharma")

    def test_possessive_employee_name_match(self):
        f = extract_canonical_filters("Priya's travel expenses", dataset_employees=self.employees)
        self.assertEqual(f["employee"], "Priya Sharma")

    def test_all_expenses_for_will_smith_in_may_2026(self):
        f = extract_canonical_filters("all expenses for Will Smith in May 2026", dataset_employees=["Will Smith", "Priya Sharma"])
        self.assertEqual(f["employee"], "Will Smith")
        self.assertEqual(f["time_period_label"], "may 2026")
        self.assertEqual(f["start_date"], "2026-05-01")
        self.assertEqual(f["end_date"], "2026-05-31")

    def test_expenses_for_mark_with_mark_davis_dataset(self):
        f = extract_canonical_filters("expenses for Mark", dataset_employees=["Mark Davis"])
        self.assertEqual(f["employee"], "Mark Davis")

    def test_all_expenses_for_mark_davis(self):
        f = extract_canonical_filters("all expenses for Mark Davis", dataset_employees=["Mark Davis"])
        self.assertEqual(f["employee"], "Mark Davis")

    def test_all_travel_expenses_for_may_brown_in_june_2026(self):
        f = extract_canonical_filters("all travel expenses for May Brown in June 2026", dataset_employees=["May Brown"])
        self.assertEqual(f["employee"], "May Brown")
        self.assertEqual(f["time_period_label"], "june 2026")
        self.assertEqual(f["start_date"], "2026-06-01")
        self.assertEqual(f["end_date"], "2026-06-30")


class TestZeroMatchExplanation(BaseMilestone2TestCase):
    """
    R4 Zero-match diagnostic explanation tests:
    Evaluates multi-dimensional bottleneck detection when 0 records match.
    """

    def test_zero_match_future_date_explanation(self):
        filters: ParsedFilters = {
            "start_date": "2099-01-01",
            "end_date": "2099-12-31",
            "expense_type": "all",
            "time_period_label": "2099",
            "employee": None,
            "raw_prompt": "expenses for 2099",
        }
        msg = explain_zero_match(self.sample_expenses, filters, location_supported=True)
        self.assertIn("No records found between 2099-01-01 and 2099-12-31", msg)
        self.assertIn("2026-08", msg)

    def test_zero_match_nonexistent_employee_explanation(self):
        filters: ParsedFilters = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "expense_type": "all",
            "time_period_label": "August 2026",
            "employee": "Zaphod Beeblebrox",
            "raw_prompt": "expenses for Zaphod Beeblebrox",
        }
        msg = explain_zero_match(self.sample_expenses, filters, location_supported=True)
        self.assertIn("No records found for employee 'Zaphod Beeblebrox'", msg)
        self.assertIn("Ravi Kumar", msg)

    def test_zero_match_category_mismatch_explanation(self):
        filters: ParsedFilters = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "expense_type": "all",
            "category": "Submarines",
            "time_period_label": "August 2026",
            "employee": None,
            "raw_prompt": "submarine expenses",
        }
        msg = explain_zero_match(self.sample_expenses, filters, location_supported=True)
        self.assertIn("No records found for category 'Submarines'", msg)

    def test_zero_match_travel_category_mismatch_explanation(self):
        # Dataset with only supplies and equipment
        non_travel_expenses = [
            {"date": "2026-08-01", "employee": "Ravi Kumar", "category": "Supplies", "amount": 100.0},
            {"date": "2026-08-02", "employee": "Ravi Kumar", "category": "Equipment", "amount": 200.0},
        ]
        filters: ParsedFilters = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "expense_type": "travel",
            "time_period_label": "August 2026",
            "employee": None,
            "raw_prompt": "travel expenses",
        }
        msg = explain_zero_match(non_travel_expenses, filters, location_supported=True)
        self.assertIn("No travel expenses found", msg)
        self.assertIn("Equipment", msg)

    def test_zero_match_unsupported_location_explanation(self):
        filters: ParsedFilters = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "expense_type": "all",
            "location": "Paris",
            "time_period_label": "August 2026",
            "employee": None,
            "raw_prompt": "expenses in Paris",
        }
        msg = explain_zero_match(self.sample_expenses, filters, location_supported=False)
        self.assertIn("Location filtering was requested for 'Paris', but the active dataset does not support location data", msg)

    def test_zero_match_node_execution_sets_explanation_and_count_zero(self):
        """Test that node execution on a zero-match query cleanly halts and sets diagnostic fields."""
        state: AgentState = {
            "user_request": "expenses for Zaphod Beeblebrox in August 2026",
            "dataset_id": self.dataset_id,
            "dataset_version": 1,
            "expenses": self.saved_records,
            "workflow_status": [],
        }
        res = expense_analysis_agent_node(state)

        self.assertEqual(res.get("filter_match_count"), 0)
        self.assertEqual(res.get("filtered_expenses"), [])
        self.assertIsNotNone(res.get("zero_match_explanation"))
        self.assertIn("Zaphod Beeblebrox", res.get("zero_match_explanation"))
        self.assertTrue(bool(res.get("error")))


class TestLocationSchemaNormalization(BaseMilestone2TestCase):
    """
    R5 Location schema normalization & absent location resilience:
    - Normalizes 'city' or 'destination' to canonical 'location' without data fabrication.
    - Gracefully handles datasets lacking location support.
    """

    def test_mumbai_city_column_normalized_to_location(self):
        records = [
            {"date": "2026-08-01", "employee": "Ravi Kumar", "city": "Mumbai", "amount": 100.0},
            {"date": "2026-08-02", "employee": "Priya Sharma", "city": "Mumbai", "amount": 200.0},
        ]
        norm_records, supported = normalize_expense_columns(records)
        self.assertTrue(supported, "Dataset with 'city' should report location_supported = True")
        self.assertEqual(norm_records[0]["location"], "Mumbai")
        self.assertEqual(norm_records[1]["location"], "Mumbai")
        # Ensure original column 'city' is preserved
        self.assertEqual(norm_records[0]["city"], "Mumbai")

    def test_delhi_destination_column_normalized_to_location(self):
        records = [
            {"date": "2026-08-01", "employee": "Ravi Kumar", "destination": "Delhi", "amount": 100.0},
            {"date": "2026-08-02", "employee": "Priya Sharma", "destination": "Delhi", "amount": 200.0},
        ]
        norm_records, supported = normalize_expense_columns(records)
        self.assertTrue(supported, "Dataset with 'destination' should report location_supported = True")
        self.assertEqual(norm_records[0]["location"], "Delhi")
        self.assertEqual(norm_records[1]["location"], "Delhi")

    def test_absent_location_handled_gracefully(self):
        records = [
            {"date": "2026-08-01", "employee": "Ravi Kumar", "amount": 100.0},
            {"date": "2026-08-02", "employee": "Priya Sharma", "amount": 200.0},
        ]
        norm_records, supported = normalize_expense_columns(records)
        self.assertFalse(supported, "Dataset lacking location headers should report location_supported = False")
        self.assertIsNone(norm_records[0]["location"], "Absent location must remain None (no fabrication)")
        self.assertIsNone(norm_records[1]["location"], "Absent location must remain None (no fabrication)")

    def test_retrieve_from_db_graceful_location_bypass(self):
        """
        When location is requested on a dataset with NO location support,
        graceful_location=True bypasses the location WHERE clause so date,
        employee, and category filters return matching rows instead of 0 rows.
        """
        # Create dataset without location
        ds_no_loc = create_or_get_dataset(
            name="No_Location_Dataset",
            file_hash="hash_no_loc_999",
            row_count=2,
            schema={"columns": ["date", "employee", "amount"]},
            db_path=self.db_path,
        )
        ds_id = ds_no_loc["dataset_id"]

        no_loc_records = [
            {"date": "2026-08-01", "employee": "Ravi Kumar", "category": "Meals", "amount": 100.0},
            {"date": "2026-08-02", "employee": "Priya Sharma", "category": "Meals", "amount": 200.0},
        ]
        save_expenses(no_loc_records, dataset_id=ds_id, dataset_version=1, source_name="no_loc.csv", db_path=self.db_path)

        # Confirm helper detects lack of location support
        self.assertFalse(dataset_has_location_support(ds_id, db_path=self.db_path))

        # Retrieve with location="Mumbai" and graceful_location=True
        retrieved = retrieve_expenses_from_db(
            dataset_id=ds_id,
            location="Mumbai",
            graceful_location=True,
            db_path=self.db_path,
        )
        self.assertEqual(len(retrieved), 2, "Graceful location fallback must return matching records")

    def test_retrieve_from_db_strict_location_when_supported(self):
        """When location is supported, strict filtering applies."""
        ds_loc = create_or_get_dataset(
            name="Supported_Location_Dataset",
            file_hash="hash_supported_loc_111",
            row_count=2,
            schema={"columns": ["date", "employee", "location", "amount"]},
            db_path=self.db_path,
        )
        ds_id = ds_loc["dataset_id"]

        loc_records = [
            {"date": "2026-08-01", "employee": "Ravi Kumar", "location": "Mumbai", "amount": 100.0},
            {"date": "2026-08-02", "employee": "Priya Sharma", "location": "Pune", "amount": 200.0},
        ]
        save_expenses(loc_records, dataset_id=ds_id, dataset_version=1, source_name="loc.csv", db_path=self.db_path)

        self.assertTrue(dataset_has_location_support(ds_id, db_path=self.db_path))

        retrieved_mumbai = retrieve_expenses_from_db(
            dataset_id=ds_id,
            location="Mumbai",
            graceful_location=True,
            db_path=self.db_path,
        )
        self.assertEqual(len(retrieved_mumbai), 1)
        self.assertEqual(retrieved_mumbai[0]["location"], "Mumbai")

    def test_filter_expenses_location_graceful_fallback(self):
        """filter_expenses respects location_supported flag."""
        records_no_loc = [
            {"date": "2026-08-01", "employee": "Ravi Kumar", "category": "Meals", "amount": 100.0},
        ]
        filtered = filter_expenses(
            records_no_loc,
            start_date="2026-08-01",
            end_date="2026-08-31",
            location="Mumbai",
            location_supported=False,
        )
        self.assertEqual(len(filtered), 1, "Absent location support must not drop records in filter_expenses")

    def test_mixed_casing_headers_normalized_to_location(self):
        records = [
            {"CITY": "Mumbai", "amount": 100},
            {"Destination": "Delhi", "amount": 200},
            {"Location": "Bangalore", "amount": 300},
        ]
        norm_records, supported = normalize_expense_columns(records)
        self.assertTrue(supported, "Mixed casing headers (CITY, Destination, Location) should have location support")
        self.assertEqual([r["location"] for r in norm_records], ["Mumbai", "Delhi", "Bangalore"])

    def test_save_expenses_mixed_casing_headers_persists_location(self):
        records = [
            {"CITY": "Mumbai", "amount": 100},
            {"Destination": "Delhi", "amount": 200},
            {"Location": "Bangalore", "amount": 300},
        ]
        save_res = save_expenses(records, dataset_id=self.dataset_id, dataset_version=1, db_path=self.db_path)
        self.assertEqual(save_res["inserted"] + save_res["skipped_duplicates"], 3)
        self.assertTrue(dataset_has_location_support(self.dataset_id, db_path=self.db_path))
        rows_bangalore = retrieve_expenses_from_db(dataset_id=self.dataset_id, location="Bangalore", db_path=self.db_path)
        self.assertEqual(len(rows_bangalore), 1)
        self.assertEqual(rows_bangalore[0]["location"], "Bangalore")
        rows_delhi = retrieve_expenses_from_db(dataset_id=self.dataset_id, location="Delhi", db_path=self.db_path)
        self.assertEqual(len(rows_delhi), 1)
        self.assertEqual(rows_delhi[0]["location"], "Delhi")

        records_with_loc = [
            {"date": "2026-08-01", "employee": "Ravi Kumar", "location": "Pune", "amount": 100.0},
        ]
        filtered_strict = filter_expenses(
            records_with_loc,
            start_date="2026-08-01",
            end_date="2026-08-31",
            location="Mumbai",
            location_supported=True,
        )
        self.assertEqual(len(filtered_strict), 0, "Supported location mismatch must filter out record")


class TestCanonicalParsedFiltersPropagation(BaseMilestone2TestCase):
    """
    R4 State consistency & propagation tests:
    - ParsedFilters serialization roundtrip.
    - Consistency across filter_expenses, retrieve_expenses_from_db, and report_runs.
    """

    def test_parsed_filters_json_roundtrip(self):
        f: ParsedFilters = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "time_period_label": "August 2026",
            "expense_type": "travel",
            "employee": "Ravi Kumar",
            "category": "Flight",
            "merchant": "Air India",
            "location": "Mumbai",
            "raw_prompt": "August travel for Ravi Kumar",
        }
        serialized = json.dumps(f)
        deserialized = json.loads(serialized)
        self.assertEqual(deserialized, f)

    def test_filter_expenses_accepts_parsed_filters_dict(self):
        filters: ParsedFilters = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "expense_type": "travel",
            "employee": "Ravi Kumar",
            "category": "Flight",
            "location": "Mumbai",
            "raw_prompt": "test prompt",
        }
        filtered = filter_expenses(self.sample_expenses, filters=filters)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["category"], "Flight")
        self.assertEqual(filtered[0]["employee"], "Ravi Kumar")

    def test_retrieve_expenses_accepts_parsed_filters_dict(self):
        filters: ParsedFilters = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "expense_type": "travel",
            "employee": "Priya Sharma",
            "category": "Meals",
            "location": "Mumbai",
            "raw_prompt": "test prompt",
        }
        retrieved = retrieve_expenses_from_db(
            dataset_id=self.dataset_id,
            filters=filters,
            db_path=self.db_path,
        )
        self.assertEqual(len(retrieved), 1)
        self.assertEqual(retrieved[0]["employee"], "Priya Sharma")
        self.assertEqual(retrieved[0]["category"], "Meals")

    def test_report_runs_persists_parsed_filters(self):
        filters: ParsedFilters = {
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "time_period_label": "August 2026",
            "expense_type": "all",
            "employee": None,
            "category": None,
            "merchant": None,
            "location": "Mumbai",
            "raw_prompt": "all expenses for August in Mumbai",
        }
        report_record = {
            "report_id": "REP-M2-TEST-001",
            "user_request": "all expenses for August in Mumbai",
            "filters": filters,
            "transaction_ids": ["REC-1", "REC-2"],
            "transaction_count": 2,
            "grand_total": 6650.0,
            "validation_status": "Clear",
            "report_file_path": "reports/test.pdf",
            "human_review_status": "Not Required",
        }
        save_report_run(
            report_record,
            dataset_id=self.dataset_id,
            dataset_version=1,
            db_path=self.db_path,
        )

        history = get_report_history(dataset_id=self.dataset_id, db_path=self.db_path)
        self.assertEqual(len(history), 1)
        saved_run = history[0]
        self.assertEqual(saved_run["report_id"], "REP-M2-TEST-001")
        self.assertEqual(saved_run["filters"]["location"], "Mumbai")
        self.assertIsNone(saved_run["filters"]["employee"])
        self.assertEqual(saved_run["filters"]["expense_type"], "all")

    def test_node_propagation_in_graph_execution(self):
        """
        Verify that canonical fields propagate cleanly through:
        expense_analysis_agent_node -> validation_agent_node -> report_generation_agent_node
        """
        init_state: AgentState = {
            "user_request": "all expenses for Ravi Kumar August 2026",
            "dataset_id": self.dataset_id,
            "dataset_version": 1,
            "expenses": self.saved_records,
            "workflow_status": [],
        }

        # Step 1: Expense Analysis Agent
        out1 = expense_analysis_agent_node(init_state)
        self.assertIn("parsed_filters", out1)
        self.assertIn("filter_match_count", out1)
        self.assertEqual(out1["filter_match_count"], 2)
        self.assertEqual(out1["dataset_id"], self.dataset_id)
        self.assertEqual(out1["dataset_version"], 1)

        # Merge state
        merged_state = {**init_state, **out1}

        # Step 2: Validation Agent
        out2 = validation_agent_node(merged_state)
        merged_state.update(out2)
        # Validation Agent maintains status
        self.assertIn("validation_findings", merged_state)

        # Step 3: Report Generation Agent
        out3 = report_generation_agent_node(merged_state)
        self.assertIn("report_payload", out3)
        payload = out3["report_payload"]
        self.assertEqual(payload["dataset_id"], self.dataset_id)
        self.assertEqual(payload["dataset_version"], 1)
        self.assertIsNotNone(payload["parsed_filters"])
        self.assertEqual(payload["parsed_filters"]["employee"], "Ravi Kumar")


if __name__ == "__main__":
    unittest.main()
