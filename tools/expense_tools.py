"""
Expense data retrieval and filtering tools.

These tools handle reading expense data from CSV and applying
date/type filters. All operations are deterministic Python/Pandas
— the LLM is never used for data filtering or manipulation.
"""

import pandas as pd
from datetime import datetime
from typing import Optional, Any, Dict, List, Tuple


def _extract_location_from_dict(rec: dict) -> Optional[str]:
    """Extract location from record dict case-insensitively checking location, city, destination."""
    if not isinstance(rec, dict):
        return None
    for target in ("location", "city", "destination"):
        for k, v in rec.items():
            if str(k).strip().lower() == target:
                if v is not None and str(v).strip() not in ("", "nan", "null", "none", "None"):
                    return str(v).strip()
    return None


def normalize_expense_columns(records: list[dict]) -> tuple[list[dict], bool]:
    """
    Normalize column names across expense records:
    - Standardizes 'city' or 'destination' to canonical 'location' field without data fabrication.
    - Inspects dictionary keys case-insensitively (e.g. CITY, Destination, Location).
    - Detects whether dataset actually supports location data.
    - If location is absent, keeps location as None and flags has_location_support = False.
    
    Args:
        records: List of raw expense dictionaries.
        
    Returns:
        tuple[list[dict], bool]: (normalized_records, has_location_support)
    """
    if not records:
        return [], False

    has_location_support = any(
        _extract_location_from_dict(rec) is not None
        for rec in records
    )

    normalized_records = []
    for rec in records:
        rec_copy = dict(rec)
        loc_val = _extract_location_from_dict(rec_copy)
        rec_copy["location"] = loc_val
        normalized_records.append(rec_copy)

    return normalized_records, has_location_support


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
            .astype(str)
            .str.replace("₹", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.strip()
        )
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    
    records = df.to_dict(orient="records")
    
    # Convert Timestamps to ISO strings and handle NaNs safely
    for record in records:
        if isinstance(record.get("date"), pd.Timestamp):
            record["date"] = record["date"].strftime("%Y-%m-%d")
        elif pd.isna(record.get("date")):
            record["date"] = ""

        # Amount conversion
        if pd.isna(record.get("amount")):
            record["amount"] = None
        else:
            try:
                record["amount"] = float(record["amount"])
            except (ValueError, TypeError):
                record["amount"] = None
    
    return records


def filter_expenses(
    expenses: list[dict],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    expense_type: Optional[str] = None,
    employee_name: Optional[str] = None,
    category: Optional[str] = None,
    location: Optional[str] = None,
    filters: Optional[dict] = None,
    location_supported: Optional[bool] = None,
    **kwargs: Any,
) -> list[dict]:
    """
    Filter expenses by date range and optionally by expense type, employee, category, and location.
    Accepts either direct arguments or a canonical filters / ParsedFilters dictionary.
    
    Args:
        expenses: List of expense dicts (from get_expenses or SQLite).
        start_date: Start date in YYYY-MM-DD format (inclusive).
        end_date: End date in YYYY-MM-DD format (inclusive).
        expense_type: Optional filter like "travel". If "travel",
                      includes Flight, Transport, Accommodation, Meals.
                      If None or "all", returns everything in the date range.
        employee_name: Optional employee name filter (case-insensitive).
        category: Optional specific category filter (e.g. "Flight").
        location: Optional location filter (e.g. "Mumbai").
        filters: Optional canonical ParsedFilters / dict object.
        location_supported: Optional flag indicating whether dataset supports location.
    
    Returns:
        Filtered list of expense dicts.
    """
    # Unpack canonical filters dictionary if supplied
    if filters:
        if "start_date" in filters and filters["start_date"]:
            start_date = filters["start_date"]
        if "end_date" in filters and filters["end_date"]:
            end_date = filters["end_date"]
        if "expense_type" in filters and filters["expense_type"]:
            expense_type = filters["expense_type"]
        if "employee" in filters:
            employee_name = filters["employee"]
        elif "employee_name" in filters:
            employee_name = filters["employee_name"]
        if "category" in filters:
            category = filters["category"]
        if "location" in filters:
            location = filters["location"]

    start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
    end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else None
    
    # Travel-related categories
    travel_categories = {
        "flight", "transport", "accommodation", "meals", "travel",
        "lodging", "hotel", "taxi", "airfare", "transit", "cab"
    }
    
    # Detect dataset location support if not explicitly passed
    if location_supported is None:
        has_location_data = any(
            _extract_location_from_dict(exp) is not None
            for exp in expenses
        )
    else:
        has_location_data = location_supported

    filtered = []
    for exp in expenses:
        # Respect is_excluded flag: omit excluded records unless explicitly requested
        if not kwargs.get("include_excluded", False):
            if exp.get("is_excluded") in (1, True, "1", "true"):
                continue

        # Check expense date safely (supports 'date' or 'expense_date')
        date_str = str(exp.get("date") if exp.get("date") is not None else exp.get("expense_date", "")).strip()
        valid_date = False
        try:
            exp_date = datetime.strptime(date_str, "%Y-%m-%d")
            valid_date = True
        except (ValueError, TypeError):
            valid_date = False

        # If date is valid, apply date range filter
        if valid_date:
            if start and end and not (start <= exp_date <= end):
                continue
            elif start and not end and exp_date < start:
                continue
            elif end and not start and exp_date > end:
                continue
        else:
            # If date is null, empty, or unparseable, do NOT crash.
            # Keep as candidate so Validation Agent can audit it and request human input/exclusion!
            pass
        
        # Expense type check
        if expense_type and expense_type.lower() == "travel":
            exp_cat = str(exp.get("category", "")).lower().strip()
            # If category is provided, check if in travel categories. If missing, keep for validation!
            if exp_cat and exp_cat not in travel_categories:
                continue

        # Specific category check
        if category and category.strip():
            exp_cat = str(exp.get("category", "")).lower().strip()
            if exp_cat and exp_cat != category.strip().lower():
                continue
        
        # Employee filter check
        if employee_name and employee_name.strip():
            emp_target = employee_name.lower().strip()
            exp_emp = str(exp.get("employee", "")).lower().strip()
            if exp_emp and emp_target not in exp_emp and exp_emp not in emp_target:
                continue

        # Location check
        if location and location.strip():
            if has_location_data:
                rec_loc = (_extract_location_from_dict(exp) or "").strip().lower()
                if rec_loc and rec_loc != location.strip().lower():
                    continue
                elif not rec_loc:
                    continue
            else:
                # Location unsupported in dataset: allow date, category, and employee filtering to proceed
                pass
        
        filtered.append(exp)
    
    return filtered
