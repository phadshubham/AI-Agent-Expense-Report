"""
Expense validation and categorization tools.

Validates expense records for completeness and correctness.
Categorization uses existing category data or rule-based fallback.
Supports structured validation findings for the Validation Agent.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
import math


# Keyword-to-category mapping for rule-based categorization
CATEGORY_KEYWORDS = {
    "flight": ["flight", "airline", "indigo", "air india", "spicejet", "vistara", "airways"],
    "transport": ["taxi", "cab", "uber", "ola", "rapido", "auto", "metro", "bus", "transport"],
    "accommodation": ["hotel", "stay", "marriott", "hyatt", "oyo", "taj", "resort", "lodge", "inn"],
    "meals": ["dinner", "lunch", "breakfast", "restaurant", "food", "cafe", "bistro", "meal", "grill"],
}


def categorize_expenses(expenses: list[dict]) -> list[dict]:
    """
    Categorize expenses using existing category data or rule-based inference.
    
    If an expense already has a valid category, it is preserved.
    If the category is missing or empty, we attempt to infer it from
    the description and merchant fields using keyword matching.
    
    Args:
        expenses: List of expense dicts.
        
    Returns:
        Same list with 'category' field ensured on all records.
    """
    categorized = []
    for exp in expenses:
        exp_copy = dict(exp)
        category = exp_copy.get("category", "").strip()
        
        if not category:
            # Attempt rule-based categorization
            text = f"{exp_copy.get('description', '')} {exp_copy.get('merchant', '')}".lower()
            inferred = _infer_category(text)
            exp_copy["category"] = inferred
        
        categorized.append(exp_copy)
    
    return categorized


def _infer_category(text: str) -> str:
    """Infer category from description/merchant text using keyword matching."""
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                return category.capitalize()
    return "Other"


def validate_expenses(expenses: list[dict]) -> list[dict]:
    """
    Validate expense records and return structured issues found.
    
    Checks for:
    - Missing receipt
    - Missing or non-positive amount
    - Missing date
    - Missing description
    - Missing category
    - Duplicate transactions (same date + merchant + amount)
    
    Args:
        expenses: List of expense dicts to validate.
        
    Returns:
        List of issue dicts with structured keys:
        'index', 'record_id', 'expense', 'issue_type', 'field_name',
        'severity', 'status', 'requires_human_review', 'message'.
    """
    issues = []
    seen = set()
    
    for i, exp in enumerate(expenses):
        if not exp.get("record_id"):
            exp["record_id"] = f"rec_{i}"
        rec_id = exp["record_id"]

        # --- Missing Receipt ---
        receipt = str(exp.get("receipt_status", "")).strip().lower()
        if receipt in ("missing", "", "no", "n/a", "none", "nan"):
            raw_amt = exp.get("amount", 0)
            try:
                amt_disp = float(raw_amt) if raw_amt is not None and not math.isnan(float(raw_amt)) else 0.0
            except:
                amt_disp = 0.0
            issues.append({
                "index": i,
                "record_id": rec_id,
                "expense": exp,
                "issue_type": "missing_receipt",
                "field_name": "receipt_status",
                "severity": "medium",
                "status": "unresolved",
                "requires_human_review": True,
                "message": (
                    f"Missing receipt for '{exp.get('description', 'Unknown')}' — "
                    f"₹{amt_disp:,.2f}"
                ),
            })
        
        # --- Missing or Invalid Amount ---
        amount = exp.get("amount")
        amt_num = None
        if amount is not None:
            try:
                amt_num = float(amount)
                if math.isnan(amt_num) or math.isinf(amt_num):
                    amt_num = None
            except (ValueError, TypeError):
                amt_num = None

        if amt_num is None or amt_num <= 0:
            issues.append({
                "index": i,
                "record_id": rec_id,
                "expense": exp,
                "issue_type": "invalid_amount",
                "field_name": "amount",
                "severity": "high",
                "status": "unresolved",
                "requires_human_review": True,
                "message": (
                    f"Null or invalid amount for '{exp.get('description', 'Unknown')}' "
                    f"(Recorded: {amount if amt_num is not None else 'NULL'}). "
                    "Input a valid value or exclude from counting."
                ),
            })
        
        # --- Missing or Invalid Date ---
        exp_date_raw = exp.get("date")
        exp_date = str(exp_date_raw or "").strip()
        if not exp_date or exp_date.lower() in ("none", "nan", "nat", "null", "<na>", ""):
            issues.append({
                "index": i,
                "record_id": rec_id,
                "expense": exp,
                "issue_type": "missing_date",
                "field_name": "date",
                "severity": "high",
                "status": "unresolved",
                "requires_human_review": True,
                "message": f"Missing date for '{exp.get('description', 'Unknown')}'. Input date or exclude from counting.",
            })
        else:
            clean_date = exp_date.split("T")[0].strip()
            date_valid = False
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    datetime.strptime(clean_date, fmt)
                    date_valid = True
                    break
                except (ValueError, TypeError):
                    continue

            if not date_valid:
                issues.append({
                    "index": i,
                    "record_id": rec_id,
                    "expense": exp,
                    "issue_type": "invalid_date",
                    "field_name": "date",
                    "severity": "high",
                    "status": "unresolved",
                    "requires_human_review": True,
                    "message": (
                        f"Invalid date '{exp_date}' for '{exp.get('description', 'Unknown')}'. "
                        "Expected valid calendar date in YYYY-MM-DD format (e.g. 2026-02-29 is not a leap year)."
                    ),
                })
        
        # --- Missing Description ---
        desc_val = str(exp.get("description", "")).strip()
        if not desc_val or desc_val.lower() in ("none", "nan", "null", "<na>"):
            issues.append({
                "index": i,
                "record_id": rec_id,
                "expense": exp,
                "issue_type": "missing_description",
                "field_name": "description",
                "severity": "low",
                "status": "unresolved",
                "requires_human_review": True,
                "message": f"Missing description for expense at index {i}",
            })
        
        # --- Missing Category ---
        if not str(exp.get("category", "")).strip():
            issues.append({
                "index": i,
                "record_id": rec_id,
                "expense": exp,
                "issue_type": "missing_category",
                "field_name": "category",
                "severity": "low",
                "status": "unresolved",
                "requires_human_review": True,
                "message": (
                    f"Missing category: {exp.get('description', 'Unknown')}"
                ),
            })
        
        # --- Duplicate Detection ---
        dedup_key = (
            str(exp.get("date", "")).strip(),
            str(exp.get("merchant", "")).lower().strip(),
            str(exp.get("amount", "")).strip(),
        )
        if dedup_key in seen:
            issues.append({
                "index": i,
                "record_id": rec_id,
                "expense": exp,
                "issue_type": "duplicate",
                "field_name": "duplicate",
                "severity": "high",
                "status": "unresolved",
                "requires_human_review": True,
                "message": (
                    f"Possible duplicate: {exp.get('description', 'Unknown')} — "
                    f"{exp.get('merchant', '')} — ₹{float(exp.get('amount', 0) or 0):,.0f}"
                ),
            })
        else:
            seen.add(dedup_key)
    
    return issues


def revalidate_single_expense(expense: dict) -> list[dict]:
    """
    Validate a single expense record after user editing/correction.
    Returns list of remaining issue dicts (empty if record is completely valid).
    """
    return validate_expenses([expense])
