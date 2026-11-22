"""
Refactored unit tests for core expense processing tools:
filtering, categorization, validation, arithmetic totals, intent extraction, and PDF generation.
"""

import os
from tools.expense_tools import get_expenses, filter_expenses
from tools.validation_tools import validate_expenses, categorize_expenses
from tools.calculation_tools import calculate_totals
from tools.pdf_tools import generate_pdf
from agent import _regex_extract_intent, _resolve_date_range


def test_get_expenses_loads_dataset(sample_csv_path):
    expenses = get_expenses(sample_csv_path)
    assert len(expenses) >= 150
    assert "employee" in expenses[0]
    assert "amount" in expenses[0]


def test_filter_expenses_august_travel(sample_expenses):
    filtered = filter_expenses(sample_expenses, "2026-08-01", "2026-08-31", "travel")
    assert len(filtered) > 0
    for exp in filtered:
        assert "2026-08" in exp["date"]


def test_categorize_expenses(sample_expenses):
    filtered = filter_expenses(sample_expenses, "2026-08-01", "2026-08-31", "travel")
    categorized = categorize_expenses(filtered)
    assert len(categorized) == len(filtered)
    for exp in categorized:
        assert "category" in exp
        assert exp["category"] in ("Flight", "Accommodation", "Meals", "Transport", "Other")


def test_validate_expenses(sample_expenses):
    filtered = filter_expenses(sample_expenses, "2026-08-01", "2026-08-31", "travel")
    categorized = categorize_expenses(filtered)
    issues = validate_expenses(categorized)
    assert isinstance(issues, list)
    for issue in issues:
        assert "issue_type" in issue
        assert "severity" in issue


def test_calculate_totals(sample_expenses):
    filtered = filter_expenses(sample_expenses, "2026-08-01", "2026-08-31", "travel")
    categorized = categorize_expenses(filtered)
    totals = calculate_totals(categorized)
    assert "grand_total" in totals
    assert totals["grand_total"] > 0
    assert "category_totals" in totals
    assert "transaction_count" in totals
    assert totals["transaction_count"] == len(categorized)


def test_generate_pdf_single_employee(sample_expenses, tmp_path):
    filtered = filter_expenses(sample_expenses, "2026-08-01", "2026-08-31", "travel", employee_name="Priya Sharma")
    categorized = categorize_expenses(filtered)
    totals = calculate_totals(categorized)
    issues = validate_expenses(categorized)
    
    out_dir = str(tmp_path / "reports_single")
    pdf_path = generate_pdf(
        expenses=categorized,
        totals=totals,
        missing_data=issues,
        employee_name="Priya Sharma",
        start_date="2026-08-01",
        end_date="2026-08-31",
        output_dir=out_dir,
    )
    assert os.path.exists(pdf_path)
    assert os.path.getsize(pdf_path) > 1000


def test_intent_extraction_default():
    intent = _regex_extract_intent("Generate travel expense report for last month")
    assert intent["expense_type"] == "travel"
    start, end = _resolve_date_range(intent["time_period"])
    assert start and end


def test_intent_extraction_dynamic_employee():
    intent = _regex_extract_intent("generate travel report for Jonathan Davis")
    assert intent["employee_name"] == "Jonathan Davis"


def test_intent_extraction_typo_tolerance():
    intent_with_typo = _regex_extract_intent("generate augest report for Priya Sharma")
    assert intent_with_typo["employee_name"] == "Priya Sharma"
    assert intent_with_typo["time_period"] == "august"
    p_start, p_end = _resolve_date_range(intent_with_typo["time_period"])
    assert p_start == "2026-08-01"
    assert p_end == "2026-08-31"


def test_multi_employee_filtering(sample_expenses):
    priya_aug = filter_expenses(sample_expenses, "2026-08-01", "2026-08-31", "travel", employee_name="Priya Sharma")
    assert len(priya_aug) > 0
    for r in priya_aug:
        assert r["employee"] == "Priya Sharma"


def test_generate_pdf_multi_employee(sample_expenses, tmp_path):
    filtered = filter_expenses(sample_expenses, "2026-08-01", "2026-08-31", "travel")
    categorized = categorize_expenses(filtered)
    totals = calculate_totals(categorized)
    issues = validate_expenses(categorized)

    out_dir = str(tmp_path / "reports_multi")
    multi_pdf_path = generate_pdf(
        expenses=filtered,
        totals=totals,
        missing_data=issues,
        employee_name="Company Team",
        start_date="2026-08-01",
        end_date="2026-08-31",
        output_dir=out_dir,
    )
    assert os.path.exists(multi_pdf_path)
    assert os.path.getsize(multi_pdf_path) > 1000
