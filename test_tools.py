"""Quick test script for all expense tools."""
import sys
import io
import os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from tools.expense_tools import get_expenses, filter_expenses
from tools.validation_tools import validate_expenses, categorize_expenses
from tools.calculation_tools import calculate_totals
from tools.pdf_tools import generate_pdf
from agent import _regex_extract_intent, _resolve_date_range

# Test 1: Read expenses
expenses = get_expenses("data/expenses.csv")
print(f"[1] Loaded {len(expenses)} expenses")
assert len(expenses) >= 150

# Test 2: Filter (August 2026)
filtered = filter_expenses(expenses, "2026-08-01", "2026-08-31", "travel")
print(f"\n[2] Filtered to {len(filtered)} August travel expenses")
assert len(filtered) > 0

# Test 3: Categorize
categorized = categorize_expenses(filtered)
print(f"\n[3] Categorized {len(categorized)} expenses")
assert len(categorized) == len(filtered)

# Test 4: Validate
issues = validate_expenses(categorized)
print(f"\n[4] Found {len(issues)} validation issues")

# Test 5: Calculate
totals = calculate_totals(categorized)
print(f"\n[5] Grand total: ₹{totals['grand_total']:,.0f}")
for cat, amt in sorted(totals["category_totals"].items()):
    print(f"    {cat}: ₹{amt:,.0f}")
print(f"    Missing receipt total: ₹{totals['missing_receipt_total']:,.0f}")
print(f"    Transaction count: {totals['transaction_count']}")

# Test 6: Single-employee PDF generation
pdf_path = generate_pdf(
    expenses=categorized[:10],
    totals=calculate_totals(categorized[:10]),
    missing_data=issues,
    employee_name="Priya Sharma",
    start_date="2026-08-01",
    end_date="2026-08-31",
)
print(f"\n[6] Single-Employee PDF generated: {pdf_path}")
assert os.path.exists(pdf_path)

# Test 7: Default intent extraction
intent = _regex_extract_intent("Generate travel expense report for last month")
print(f"\n[7] Intent extraction (default): {intent}")
start, end = _resolve_date_range(intent["time_period"])
print(f"    Date range: {start} to {end}")

# Test 8: Dynamic employee extraction from prompt
intent_dynamic = _regex_extract_intent("generate travel report for Jonathan Davis")
print(f"\n[8] Dynamic employee extraction: {intent_dynamic}")
assert intent_dynamic["employee_name"] == "Jonathan Davis"

# Test 9: Typo tolerance ("augest" -> "august")
intent_with_typo = _regex_extract_intent("generate augest report for Priya Sharma")
print(f"\n[9] Intent extraction (person + 'augest'): {intent_with_typo}")
assert intent_with_typo["employee_name"] == "Priya Sharma"
assert intent_with_typo["time_period"] == "august"
p_start, p_end = _resolve_date_range(intent_with_typo["time_period"])
print(f"    Date range: {p_start} to {p_end}")
assert p_start == "2026-08-01" and p_end == "2026-08-31"

# Test 10: Multi-employee filtering
priya_aug = filter_expenses(expenses, "2026-08-01", "2026-08-31", "travel", employee_name="Priya Sharma")
print(f"\n[10] Priya Sharma August travel expenses: {len(priya_aug)}")
assert len(priya_aug) > 0
for r in priya_aug:
    assert r["employee"] == "Priya Sharma"

# Test 11: Multi-employee unified PDF generation
multi_pdf_path = generate_pdf(
    expenses=filtered,
    totals=totals,
    missing_data=issues,
    employee_name="Company Team",
    start_date="2026-08-01",
    end_date="2026-08-31",
)
print(f"\n[11] Unified Multi-Employee PDF generated: {multi_pdf_path}")
assert os.path.exists(multi_pdf_path)

print("\n✅ All tests passed!")
