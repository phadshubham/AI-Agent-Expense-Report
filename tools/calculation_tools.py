"""
Expense calculation tools.

All financial calculations are performed deterministically
using Python/Pandas. The LLM is never used for arithmetic.
"""

import pandas as pd


def calculate_totals(expenses: list[dict]) -> dict:
    """
    Calculate expense totals by category and overall.
    
    Args:
        expenses: List of expense dicts (filtered and validated).
        
    Returns:
        Dictionary with:
        - category_totals: {category: total_amount}
        - grand_total: float
        - transaction_count: int
        - missing_receipt_total: float
        - category_counts: {category: num_transactions}
    """
    if not expenses:
        return {
            "category_totals": {},
            "grand_total": 0.0,
            "transaction_count": 0,
            "missing_receipt_total": 0.0,
            "category_counts": {},
        }
    
    df = pd.DataFrame(expenses)
    
    # Ensure amount is numeric
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    
    # Category totals
    category_totals = df.groupby("category")["amount"].sum().to_dict()
    
    # Category transaction counts
    category_counts = df.groupby("category")["amount"].count().to_dict()
    
    # Grand total
    grand_total = float(df["amount"].sum())
    
    # Transaction count
    transaction_count = len(df)
    
    # Missing receipt total
    missing_mask = df["receipt_status"].astype(str).str.lower().isin(["missing", "", "no", "n/a"])
    missing_receipt_total = float(df.loc[missing_mask, "amount"].sum())
    
    # Employee breakdown if employee column exists
    employee_breakdown = {}
    if "employee" in df.columns:
        for emp, group in df.groupby("employee"):
            emp_name = str(emp).strip()
            if not emp_name:
                continue
            emp_cat_totals = group.groupby("category")["amount"].sum().to_dict()
            emp_cat_counts = group.groupby("category")["amount"].count().to_dict()
            emp_missing = group["receipt_status"].astype(str).str.lower().isin(["missing", "", "no", "n/a"])
            employee_breakdown[emp_name] = {
                "grand_total": float(group["amount"].sum()),
                "transaction_count": len(group),
                "category_totals": {k: float(v) for k, v in emp_cat_totals.items()},
                "category_counts": {k: int(v) for k, v in emp_cat_counts.items()},
                "missing_receipt_total": float(group.loc[emp_missing, "amount"].sum()),
            }
    
    return {
        "category_totals": {k: float(v) for k, v in category_totals.items()},
        "grand_total": grand_total,
        "transaction_count": transaction_count,
        "missing_receipt_total": missing_receipt_total,
        "category_counts": {k: int(v) for k, v in category_counts.items()},
        "employee_breakdown": employee_breakdown,
    }
