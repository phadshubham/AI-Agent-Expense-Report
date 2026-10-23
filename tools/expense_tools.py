"""
Expense data retrieval and filtering tools.

These tools handle reading expense data from CSV and applying
date/type filters. All operations are deterministic Python/Pandas
— the LLM is never used for data filtering or manipulation.
"""

import pandas as pd
from datetime import datetime
from typing import Optional


def get_expenses(csv_path: str = "data/expenses.csv") -> list[dict]:
    """
    Retrieve all expense records from the CSV database.
    
    Args:
        csv_path: Path to the expenses CSV file.
        
    Returns:
        List of expense records as dictionaries.
        
    Raises:
        FileNotFoundError: If the CSV file doesn't exist.
        ValueError: If the CSV is empty or malformed.
    """
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Expense database not found at '{csv_path}'. "
            "Please ensure the CSV file exists."
        )
    
    if df.empty:
        raise ValueError("Expense database is empty. No records found.")
    
    # Normalize column names (strip whitespace, lowercase)
    df.columns = df.columns.str.strip().str.lower()
    
    # Parse dates
    df["date"] = pd.to_datetime(df["date"], format="mixed", dayfirst=False)
    
    # Clean amount column — remove currency symbols and commas
    if df["amount"].dtype == object:
        df["amount"] = (
            df["amount"]
            .str.replace("₹", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.strip()
            .astype(float)
        )
    
    records = df.to_dict(orient="records")
    
    # Convert Timestamps to ISO strings for JSON serialization
    for record in records:
        if isinstance(record.get("date"), pd.Timestamp):
            record["date"] = record["date"].strftime("%Y-%m-%d")
    
    return records


def filter_expenses(
    expenses: list[dict],
    start_date: str,
    end_date: str,
    expense_type: Optional[str] = None,
    employee_name: Optional[str] = None,
) -> list[dict]:
    """
    Filter expenses by date range and optionally by expense type and employee.
    
    Args:
        expenses: List of expense dicts (from get_expenses).
        start_date: Start date in YYYY-MM-DD format (inclusive).
        end_date: End date in YYYY-MM-DD format (inclusive).
        expense_type: Optional filter like "travel". If "travel",
                      includes Flight, Transport, Accommodation, Meals.
                      If None or "all", returns everything in the date range.
        employee_name: Optional employee name filter (case-insensitive).
    
    Returns:
        Filtered list of expense dicts.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    # Travel-related categories
    travel_categories = {"flight", "transport", "accommodation", "meals"}
    
    filtered = []
    for exp in expenses:
        # Parse expense date
        exp_date = datetime.strptime(exp["date"], "%Y-%m-%d")
        
        # Date range check
        if not (start <= exp_date <= end):
            continue
        
        # Expense type check
        if expense_type and expense_type.lower() == "travel":
            category = exp.get("category", "").lower()
            if category not in travel_categories:
                continue
        
        # Employee filter check
        if employee_name and employee_name.strip():
            emp_target = employee_name.lower().strip()
            exp_emp = str(exp.get("employee", "")).lower().strip()
            if exp_emp and emp_target not in exp_emp and exp_emp not in emp_target:
                continue
        
        filtered.append(exp)
    
    return filtered
