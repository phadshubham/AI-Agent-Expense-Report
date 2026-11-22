"""
Pytest configuration and global test fixtures for AI Agent Expense Report Management System.
Enforces strict test isolation: all tests run against temporary isolated SQLite databases
and temporary report directories, asserting production databases are never modified.
"""

import os
import csv
import pytest
import sqlite3
from typing import Dict, Any, Generator

from tools.memory_tools import init_memory_db
from tools.expense_tools import get_expenses


PROD_MEM_DB = os.path.abspath(os.path.join("data", "expense_memory.db"))
PROD_CHK_DB = os.path.abspath(os.path.join(".checkpoints", "agent_state.db"))


def _get_file_stat(path: str):
    if os.path.exists(path):
        return (os.path.getmtime(path), os.path.getsize(path))
    return None


@pytest.fixture(autouse=True)
def isolate_test_environment(tmp_path, monkeypatch) -> Generator[Dict[str, Any], None, None]:
    """
    Global autouse fixture ensuring every test runs against an isolated temporary
    SQLite business database, isolated checkpoint DB, and isolated reports folder.
    Guarantees data/expense_memory.db and .checkpoints/agent_state.db are never touched.
    """
    temp_mem_db = str(tmp_path / "test_expense_memory.db")
    temp_chk_db = str(tmp_path / "test_agent_state.db")
    temp_reports_dir = str(tmp_path / "reports")
    os.makedirs(temp_reports_dir, exist_ok=True)

    # Initialize isolated schema
    init_memory_db(temp_mem_db)

    # Set isolation environment variables
    monkeypatch.setenv("EXPENSE_MEMORY_DB_PATH", temp_mem_db)
    monkeypatch.setenv("AGENT_CHECKPOINT_DB_PATH", temp_chk_db)
    monkeypatch.setenv("EXPENSE_REPORTS_DIR", temp_reports_dir)

    # Record pre-test state of production databases
    pre_mem_stat = _get_file_stat(PROD_MEM_DB)
    pre_chk_stat = _get_file_stat(PROD_CHK_DB)

    yield {
        "db_path": temp_mem_db,
        "checkpoint_db_path": temp_chk_db,
        "reports_dir": temp_reports_dir,
        "tmp_path": tmp_path,
    }

    # Post-test assertion: production DBs must be completely untouched
    post_mem_stat = _get_file_stat(PROD_MEM_DB)
    if pre_mem_stat is not None:
        assert post_mem_stat == pre_mem_stat, (
            f"INTEGRITY VIOLATION: Production {PROD_MEM_DB} was modified! Pre: {pre_mem_stat}, Post: {post_mem_stat}"
        )

    post_chk_stat = _get_file_stat(PROD_CHK_DB)
    if pre_chk_stat is not None:
        assert post_chk_stat == pre_chk_stat, (
            f"INTEGRITY VIOLATION: Production {PROD_CHK_DB} was modified! Pre: {pre_chk_stat}, Post: {post_chk_stat}"
        )


@pytest.fixture
def sample_csv_path() -> str:
    """Return path to standard production expenses.csv for read-only fixture inspection."""
    return os.path.abspath(os.path.join("data", "expenses.csv"))


@pytest.fixture
def sample_expenses(sample_csv_path: str):
    """Return in-memory loaded rows from sample_csv_path."""
    return get_expenses(sample_csv_path)


@pytest.fixture
def mumbai_expenses_csv(tmp_path) -> str:
    """
    Synthetic Mumbai expenses CSV containing a 'city' column ('Mumbai'),
    July/August 2026 date range, varied categories, and known total ₹48,500.
    """
    csv_path = str(tmp_path / "Mumbai_Expenses.csv")
    rows = [
        {"date": "2026-07-15", "description": "Flight BOM to DEL", "merchant": "IndiGo Airlines", "amount": 14500.0, "category": "Flight", "receipt_status": "Verified", "employee": "Priya Sharma", "payment_method": "Corporate Card", "city": "Mumbai"},
        {"date": "2026-07-16", "description": "Hotel Stay Trident", "merchant": "Trident Nariman Point", "amount": 18000.0, "category": "Accommodation", "receipt_status": "Verified", "employee": "Priya Sharma", "payment_method": "Corporate Card", "city": "Mumbai"},
        {"date": "2026-07-17", "description": "Client Dinner Taj", "merchant": "Shamiana Taj", "amount": 6200.0, "category": "Meals", "receipt_status": "Missing", "employee": "Priya Sharma", "payment_method": "Personal Card", "city": "Mumbai"},
        {"date": "2026-07-18", "description": "Airport Uber Cab", "merchant": "Uber India", "amount": 1200.0, "category": "Transport", "receipt_status": "Verified", "employee": "Priya Sharma", "payment_method": "Corporate Card", "city": "Mumbai"},
        {"date": "2026-08-02", "description": "Client Meeting Lunch", "merchant": "The Table Colaba", "amount": 4800.0, "category": "Meals", "receipt_status": "Verified", "employee": "Rahul Verma", "payment_method": "Corporate Card", "city": "Mumbai"},
        {"date": "2026-08-03", "description": "Local Taxi Client Visits", "merchant": "Mumbai Local Cabs", "amount": 1800.0, "category": "Transport", "receipt_status": "Missing", "employee": "Rahul Verma", "payment_method": "Cash", "city": "Mumbai"},
        {"date": "2026-08-04", "description": "Co-working Day Pass", "merchant": "WeWork BKC", "amount": 2000.0, "category": "Other", "receipt_status": "Verified", "employee": "Ananya Sen", "payment_method": "Corporate Card", "city": "Mumbai"},
    ]
    # Sum: 14500 + 18000 + 6200 + 1200 + 4800 + 1800 + 2000 = 48500.0
    fieldnames = ["date", "description", "merchant", "amount", "category", "receipt_status", "employee", "payment_method", "city"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


@pytest.fixture
def delhi_expenses_csv(tmp_path) -> str:
    """
    Synthetic Delhi expenses CSV containing a 'destination' column ('Delhi'),
    August 2026 dates, employees Ravi Kumar and Vikram Singh, with known total ₹36,200.
    """
    csv_path = str(tmp_path / "Delhi_Expenses.csv")
    rows = [
        {"date": "2026-08-10", "description": "Flight BLR to DEL", "merchant": "Air India", "amount": 12000.0, "category": "Flight", "receipt_status": "Verified", "employee": "Ravi Kumar", "payment_method": "Corporate Card", "destination": "Delhi"},
        {"date": "2026-08-11", "description": "Hotel Stay Aerocity", "merchant": "JW Marriott Aerocity", "amount": 15000.0, "category": "Accommodation", "receipt_status": "Verified", "employee": "Ravi Kumar", "payment_method": "Corporate Card", "destination": "Delhi"},
        {"date": "2026-08-12", "description": "Team Lunch Connaught", "merchant": "Saravana Bhavan", "amount": 3200.0, "category": "Meals", "receipt_status": "Verified", "employee": "Ravi Kumar", "payment_method": "Corporate Card", "destination": "Delhi"},
        {"date": "2026-08-13", "description": "Metro & Airport Express", "merchant": "Delhi Metro Rail", "amount": 1000.0, "category": "Transport", "receipt_status": "Verified", "employee": "Vikram Singh", "payment_method": "Corporate Card", "destination": "Delhi"},
        {"date": "2026-08-14", "description": "Client Site Meeting Cab", "merchant": "Uber India", "amount": 5000.0, "category": "Transport", "receipt_status": "Missing", "employee": "Vikram Singh", "payment_method": "Personal Card", "destination": "Delhi"},
    ]
    # Sum: 12000 + 15000 + 3200 + 1000 + 5000 = 36200.0
    fieldnames = ["date", "description", "merchant", "amount", "category", "receipt_status", "employee", "payment_method", "destination"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


@pytest.fixture
def legacy_expenses_csv(tmp_path) -> str:
    """
    Synthetic legacy format expenses CSV without location or dataset ID columns.
    """
    csv_path = str(tmp_path / "Legacy_Expenses.csv")
    rows = [
        {"date": "2026-05-10", "description": "Legacy Conference Registration", "merchant": "Tech Con India", "amount": 8000.0, "category": "Other", "receipt_status": "Verified", "employee": "Amit Patel", "payment_method": "Corporate Card"},
        {"date": "2026-05-11", "description": "Legacy Hotel Stay", "merchant": "Ginger Hotel", "amount": 4500.0, "category": "Accommodation", "receipt_status": "Verified", "employee": "Amit Patel", "payment_method": "Corporate Card"},
        {"date": "2026-05-12", "description": "Legacy Meals", "merchant": "Haldiram", "amount": 1200.0, "category": "Meals", "receipt_status": "Verified", "employee": "Amit Patel", "payment_method": "Corporate Card"},
    ]
    fieldnames = ["date", "description", "merchant", "amount", "category", "receipt_status", "employee", "payment_method"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


@pytest.fixture
def nulls_expenses_csv(tmp_path) -> str:
    """
    Synthetic CSV with null, missing, NaN, whitespace, and corrupt values
    to test null resilience (R3/F9) without crashing or silent 0.0 conversions.
    """
    csv_path = str(tmp_path / "Nulls_Expenses.csv")
    rows = [
        {"date": "2026-08-01", "description": "Valid expense", "merchant": "BookStore", "amount": "1200.00", "category": "Supplies", "receipt_status": "Verified", "employee": "Priya Sharma", "payment_method": "Card"},
        {"date": "2026-08-02", "description": "Empty amount field", "merchant": "Cafe Day", "amount": "", "category": "Meals", "receipt_status": "Missing", "employee": "Priya Sharma", "payment_method": "Cash"},
        {"date": "2026-08-03", "description": "String NaN amount", "merchant": "Office Mart", "amount": "NaN", "category": "Supplies", "receipt_status": "Missing", "employee": "Ravi Kumar", "payment_method": "Card"},
        {"date": "2026-08-04", "description": "String None amount", "merchant": "Stationery Shop", "amount": "None", "category": "Supplies", "receipt_status": "Verified", "employee": "Ravi Kumar", "payment_method": "Card"},
        {"date": "", "description": "Missing date string", "merchant": "Cab Service", "amount": "450.00", "category": "Transport", "receipt_status": "Missing", "employee": "Vikram Singh", "payment_method": "Cash"},
        {"date": "2026-08-06", "description": "Zero amount transaction", "merchant": "Free Vendor Sample", "amount": "0.0", "category": "Other", "receipt_status": "Verified", "employee": "Vikram Singh", "payment_method": "Card"},
    ]
    fieldnames = ["date", "description", "merchant", "amount", "category", "receipt_status", "employee", "payment_method"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path
