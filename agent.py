"""
Multi-Agent LangGraph Workflow for Expense Report Management.

Implements three clearly defined, collaborating agents:
1. Expense Analysis Agent:
   - Interprets natural-language requests (Qwen 3 via Ollama with regex fallback).
   - Retrieves records from SQLite persistent memory (data/expense_memory.db) or active input.
   - Deterministically filters records by period, category, and dynamic employee.
   - Categorizes records using keyword inference.
   - Produces structured expense analysis output.

2. Validation Agent:
   - Validates transactions against compliance policies (receipts, amounts, dates, duplicates).
   - Persists detected issues to SQLite memory.
   - Decides whether execution can proceed or must suspend for Human-in-the-Loop review.

3. Report Generation Agent:
   - Confirms audit and approval status (never silently approves unresolved issues).
   - Computes deterministic financial subtotals, grand totals, and employee breakdowns (Pandas).
   - Generates publication-grade PDF reports (ReportLab) with validation status badges.
   - Persists report-run metadata to SQLite memory.

Orchestrated using LangGraph StateGraph with SQLite workflow checkpointing
in .checkpoints/agent_state.db.
"""

import os
import re
import json
import uuid
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from typing import Optional, Dict, Any, List

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt

from state import AgentState, ParsedFilters
from tools.expense_tools import get_expenses, filter_expenses, normalize_expense_columns
from tools.validation_tools import validate_expenses, categorize_expenses, revalidate_single_expense
from tools.calculation_tools import calculate_totals
from tools.pdf_tools import generate_pdf
from tools.memory_tools import (
    init_memory_db,
    save_expenses,
    retrieve_expenses_from_db,
    save_validation_issues,
    update_expense_record,
    resolve_validation_issue,
    apply_reviewer_decision,
    save_report_run,
)


# ---------------------------------------------------------------------------
# LLM Setup & Natural Language Understanding
# ---------------------------------------------------------------------------

def _get_llm():
    """Initialize local LLM via Ollama. Returns None if unreachable."""
    try:
        from langchain_ollama import ChatOllama

        model_name = os.getenv("OLLAMA_MODEL", "qwen3:4b")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

        return ChatOllama(
            model=model_name,
            base_url=base_url,
            temperature=0,
            num_predict=512,
        )
    except Exception:
        return None


def _llm_extract_intent(user_request: str) -> dict:
    """Extract structured intent using Qwen 3 with regex fallback."""
    llm = _get_llm()

    if llm:
        try:
            prompt = f"""You are an expense report assistant. Extract the following from the user's request. Respond ONLY with a valid JSON object, no extra text, no markdown.

User request: "{user_request}"

Extract:
- expense_type: the type of expenses (e.g., "travel", "all"). Default "travel".
- time_period: the time period mentioned (e.g., "last month", "august 2026", "may 2026"). Default "last month".
- employee_name: the specific employee/person mentioned whose report is requested (e.g., "Priya Sharma", "Amit Patel"). Default "".

Respond with ONLY this JSON:
{{"expense_type": "...", "time_period": "...", "employee_name": "..."}}"""

            response = llm.invoke(prompt)
            content = response.content.strip()

            json_match = re.search(r'\{[^{}]+\}', content)
            if json_match:
                extracted = json.loads(json_match.group())
                emp = str(extracted.get("employee_name", "")).strip()
                if emp.lower() in {"all", "all employees", "all staff", "everyone", "none", "n/a", "null"}:
                    extracted["employee_name"] = ""
                clean_req = user_request.lower().replace("augest", "august").replace("aprl", "april")
                if (
                    re.search(r'\ball\s+(?:employees?|staff|team|workers?)\b', clean_req)
                    or re.search(r'\ball\s+(?:travel\s+)?expenses?\b', clean_req)
                    or re.search(r'\b(?:everyone|company[- ]wide)\b', clean_req)
                ) and not re.search(r'\b(?:for|of|by)\s+[A-Za-z]+(?:\s+[A-Za-z]+)?\b', user_request):
                    extracted["employee_name"] = ""
                return extracted
        except Exception:
            pass

    return _regex_extract_intent(user_request)


def _resolve_date_range(time_period: str) -> tuple[str, str]:
    """Resolve natural-language time period to (start_date, end_date) in YYYY-MM-DD."""
    today = datetime.now()
    clean_time = time_period.lower().replace("augest", "august").replace("aprl", "april")

    if clean_time == "last month":
        first_of_this_month = today.replace(day=1)
        last_month_end = first_of_this_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start.strftime("%Y-%m-%d"), last_month_end.strftime("%Y-%m-%d")

    if clean_time == "this month":
        start = today.replace(day=1)
        next_month = start + relativedelta(months=1)
        end = next_month - timedelta(days=1)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    months = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }

    for month_name, month_num in months.items():
        if month_name in clean_time:
            year_match = re.search(r'(\d{4})', clean_time)
            year = int(year_match.group(1)) if year_match else today.year
            start = datetime(year, month_num, 1)
            end = start + relativedelta(months=1) - timedelta(days=1)
            return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    # Default to last month
    first_of_this_month = today.replace(day=1)
    last_month_end = first_of_this_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    return last_month_start.strftime("%Y-%m-%d"), last_month_end.strftime("%Y-%m-%d")


def extract_canonical_filters(
    user_request: str,
    dataset_employees: Optional[List[str]] = None,
) -> ParsedFilters:
    """
    Extract canonical filter criteria from user prompt deterministically.
    - Sets employee = None for 'all expenses' or 'all employees'.
    - Dynamic employee discovery in dataset_employees without substring collision.
    - Handles typos in month names ("augest" -> "august", "aprl" -> "april").
    - Resolves date range, expense type, category, location, and merchant.
    """
    req_clean = " ".join(user_request.split())
    req_lower = req_clean.lower()
    norm_prompt = req_lower.replace("augest", "august").replace("aprl", "april")

    # 1. Global / All indicator check
    is_all_employees = bool(
        re.search(r'\ball\s+(?:employees?|staff|team|workers?)\b', norm_prompt)
        or re.search(r'\b(?:everyone|company[- ]wide|across all|whole team)\b', norm_prompt)
        or re.search(r'\ball\s+employee\s+expenses?\b', norm_prompt)
        or re.search(r'\bshow\s+all\s+(?:employee\s+)?expenses?\b', norm_prompt)
    )

    # If prompt asks for "all expenses" or "all travel expenses", only treat as all employees if not qualified by an explicit employee
    has_all_expenses = bool(
        re.search(r'\ball\s+(?:travel\s+)?expenses?\b', norm_prompt)
        or norm_prompt == "all expenses"
    )

    # 2. Expense type
    expense_type = "travel"
    if re.search(r'\btravel\b', norm_prompt):
        expense_type = "travel"
    elif re.search(r'\ball\b', norm_prompt) and re.search(r'\bexpense', norm_prompt):
        expense_type = "all"

    # 3. Time period & Date range
    time_period_label = None
    month_matches = list(
        re.finditer(
            r'\b(january|february|march|april|may|june|july|august|september|october|november|december)(?:\s+(\d{4}))?\b',
            norm_prompt,
        )
    )
    chosen_match = None
    if month_matches:
        candidate_months = []
        for m in month_matches:
            m_month = m.group(1).lower()
            is_may_person = False
            if m_month == "may":
                # Check if 'may' is part of a person's name (e.g. 'May Brown')
                start_idx, end_idx = m.span()
                post_text = req_clean[end_idx:].strip()
                if post_text and re.match(r'^[A-Z][a-z]+', post_text):
                    is_may_person = True
                pre_text = req_clean[:start_idx].strip().lower()
                if re.search(r'\b(?:for|of|by)\s*$', pre_text):
                    if (post_text and re.match(r'^[A-Za-z]+', post_text)) or (
                        dataset_employees and any(re.search(r'\bmay\b', de.lower()) for de in dataset_employees)
                    ):
                        is_may_person = True
                if dataset_employees and any(re.search(r'\bmay\s+[a-z]+', de.lower()) for de in dataset_employees):
                    if re.search(r'\bmay\s+[a-z]+', norm_prompt):
                        is_may_person = True

            if is_may_person and not m.group(2):
                # 'May' is part of a person's name without explicit year attached; omit from date matches
                pass
            else:
                candidate_months.append(m)

        if candidate_months:
            with_year = [m for m in candidate_months if m.group(2)]
            chosen_match = with_year[0] if with_year else candidate_months[0]

    if chosen_match:
        time_period_label = chosen_match.group(0).strip()
    elif "last month" in norm_prompt:
        time_period_label = "last month"
    elif "this month" in norm_prompt:
        time_period_label = "this month"
    elif "year to date" in norm_prompt or "ytd" in norm_prompt:
        time_period_label = "year to date"

    if time_period_label:
        start_date, end_date = _resolve_date_range(time_period_label)
    else:
        start_date, end_date = None, None

    # 4. Category extraction
    known_categories = {
        "flight": "Flight",
        "flights": "Flight",
        "transport": "Transport",
        "transportation": "Transport",
        "accommodation": "Accommodation",
        "hotel": "Accommodation",
        "meals": "Meals",
        "meal": "Meals",
        "food": "Meals",
        "supplies": "Supplies",
        "equipment": "Equipment",
        "entertainment": "Entertainment",
    }
    category = None
    for cat_key, cat_val in known_categories.items():
        if cat_val and re.search(r'\b' + cat_key + r'\b', norm_prompt):
            category = cat_val
            break

    # 5. Location extraction
    known_cities = ["mumbai", "delhi", "bangalore", "bengaluru", "pune", "hyderabad", "chennai", "kolkata", "goa"]
    location = None
    for city in known_cities:
        if re.search(r'\b' + city + r'\b', norm_prompt):
            location = city.capitalize()
            break
    if not location:
        loc_match = re.search(r'\b(?:in|at)\s+([A-Za-z]+)\b', req_clean)
        if loc_match:
            candidate_loc = loc_match.group(1).strip()
            loc_ignore = {
                "last", "this", "next", "month", "year",
                "january", "february", "march", "april", "may", "june",
                "july", "august", "augest", "september", "october", "november", "december",
                "travel", "all", "expenses", "expense", "report", "data", "summary"
            }
            if candidate_loc.lower() not in loc_ignore:
                location = candidate_loc.title()

    # 6. Employee Extraction & Disambiguation
    final_employee = None
    ignore_words = {
        "last", "this", "next", "month", "year", "quarter", "q1", "q2", "q3", "q4",
        "january", "february", "march", "april", "may", "june",
        "july", "august", "augest", "september", "october", "november", "december",
        "finance", "manager", "hr", "company", "travel", "all", "expenses", "expense",
        "someone", "person", "team", "everyone", "my", "our", "me", "report", "records",
        "data", "active", "total", "summary", "mumbai", "delhi", "pune", "bangalore",
        "flight", "hotel", "meals", "food", "transport", "supplies", "equipment",
        "will", "bill", "mark", "standard", "staff", "workers", "worker", "employee", "employees"
    }

    if not is_all_employees:
        candidate_emp = None
        stop_prepositions = {"in", "at", "on", "during", "from", "between", "under", "with", "for", "of", "by", "and"}
        month_names = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"}

        def _match_dataset_employee(cand_str: str) -> Optional[str]:
            if not cand_str or not dataset_employees:
                return None
            cand_clean = cand_str.strip().lower()
            # If candidate is a single-word month name followed by a year, it represents date range, not employee
            if cand_clean in month_names:
                if re.search(r'\b' + re.escape(cand_clean) + r'\s+\d{4}\b', req_clean, re.IGNORECASE):
                    return None
                if time_period_label and cand_clean == time_period_label.split()[0].lower():
                    # If this single month is already the resolved date range and prompt doesn't contain a surname
                    cand_words = cand_clean.split()
                    if len(cand_words) == 1:
                        return None

            # 1. Exact full name match
            for de in dataset_employees:
                if de.strip().lower() == cand_clean:
                    return de
            # 2. Word boundary match (e.g. "Mark" -> "Mark Davis", "Will" -> "Will Smith")
            for de in dataset_employees:
                if re.search(r'\b' + re.escape(cand_clean) + r'\b', de.strip().lower()):
                    return de
            return None

        # Attribution regex: "for Ravi Kumar", "of Priya Sharma", "by Amit"
        match_for = re.search(r'\b(?:for|of|by)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)\b', req_clean, re.IGNORECASE)
        if match_for:
            raw_cand = match_for.group(1).strip()
            cand_tokens = raw_cand.split()
            while cand_tokens and cand_tokens[-1].lower() in stop_prepositions:
                cand_tokens.pop()
            if cand_tokens:
                raw_cand = " ".join(cand_tokens)
                cand_lower = raw_cand.lower()
                cand_words = cand_lower.split()

                # Step a: Check dataset_employees match BEFORE discarding based on ignore_words
                matched_de = _match_dataset_employee(raw_cand)
                if matched_de:
                    candidate_emp = matched_de
                else:
                    # Discard candidate tokens only if the entire candidate string is in ignore_words
                    # OR all candidate tokens are in ignore_words
                    is_date_expr = cand_lower in month_names and re.search(r'\b' + re.escape(cand_lower) + r'\s+\d{4}\b', req_clean, re.I)
                    if not is_date_expr and cand_lower not in ignore_words and not all(w in ignore_words for w in cand_words):
                        candidate_emp = raw_cand.title()

        # Possessive: "Priya's expenses"
        if not candidate_emp:
            match_poss = re.search(r'\b([A-Za-z]+(?:\s+[A-Za-z]+)?)\'s\b', req_clean, re.IGNORECASE)
            if match_poss:
                raw_poss = match_poss.group(1).strip()
                cand_tokens = raw_poss.split()
                while cand_tokens and cand_tokens[-1].lower() in stop_prepositions:
                    cand_tokens.pop()
                if cand_tokens:
                    raw_poss = " ".join(cand_tokens)
                    poss_lower = raw_poss.lower()
                    poss_words = poss_lower.split()

                    matched_de = _match_dataset_employee(raw_poss)
                    if matched_de:
                        candidate_emp = matched_de
                    else:
                        is_date_expr = poss_lower in month_names and re.search(r'\b' + re.escape(poss_lower) + r'\s+\d{4}\b', req_clean, re.I)
                        if not is_date_expr and poss_lower not in ignore_words and not all(w in ignore_words for w in poss_words):
                            candidate_emp = raw_poss.title()

        # Resolve final employee
        if candidate_emp:
            # Explicit attribution preposition / possessive extracted:
            # Fix 1b: Do NOT allow has_all_expenses to block employee matching!
            if dataset_employees:
                matched_de = _match_dataset_employee(candidate_emp)
                final_employee = matched_de if matched_de else candidate_emp
            else:
                final_employee = candidate_emp
        elif not is_all_employees and not has_all_expenses:
            # Dynamic full-name matching with word boundaries from dataset_employees
            if dataset_employees:
                for de in dataset_employees:
                    de_words = de.lower().split()
                    if len(de_words) == 1 and de_words[0] in ignore_words:
                        continue
                    if re.search(r'\b' + re.escape(de.lower()) + r'\b', norm_prompt):
                        final_employee = de
                        break

    return {
        "start_date": start_date,
        "end_date": end_date,
        "time_period_label": time_period_label,
        "expense_type": expense_type,
        "employee": final_employee,
        "category": category,
        "merchant": None,
        "location": location,
        "raw_prompt": user_request,
    }


def _regex_extract_intent(user_request: str) -> dict:
    """Regex-based fallback for intent extraction (100% backward compatible)."""
    filters = extract_canonical_filters(user_request)
    return {
        "expense_type": filters.get("expense_type", "travel"),
        "time_period": filters.get("time_period_label") or "last month",
        "employee_name": filters.get("employee") or "",
    }


def explain_zero_match(
    raw_expenses: List[Dict[str, Any]],
    parsed_filters: ParsedFilters,
    location_supported: bool = True,
) -> str:
    """Analyze which filter condition(s) caused the dataset to yield 0 records."""
    if not raw_expenses:
        return "The active dataset contains 0 total records."

    start_date = parsed_filters.get("start_date")
    end_date = parsed_filters.get("end_date")
    employee = parsed_filters.get("employee")
    expense_type = parsed_filters.get("expense_type")
    category = parsed_filters.get("category")
    location = parsed_filters.get("location")

    reasons = []

    # 1. Date Range
    if start_date and end_date:
        date_matches = [
            e for e in raw_expenses
            if (e.get("date") or e.get("expense_date")) and start_date <= str(e.get("date") or e.get("expense_date"))[:10] <= end_date
        ]
        if not date_matches:
            valid_dates = [str(e.get("date") or e.get("expense_date"))[:10] for e in raw_expenses if (e.get("date") or e.get("expense_date"))]
            min_d = min(valid_dates) if valid_dates else "N/A"
            max_d = max(valid_dates) if valid_dates else "N/A"
            reasons.append(
                f"No records found between {start_date} and {end_date} (dataset dates range from {min_d} to {max_d})"
            )

    # 2. Employee
    if employee:
        emp_matches = [
            e for e in raw_expenses
            if e.get("employee") and employee.lower() in str(e.get("employee")).lower()
        ]
        if not emp_matches:
            avail_emps = sorted(list({str(e.get("employee")) for e in raw_expenses if e.get("employee")}))
            reasons.append(
                f"No records found for employee '{employee}'" + (f" (available: {', '.join(avail_emps[:5])})" if avail_emps else "")
            )

    # 3. Category / Expense Type
    if category:
        cat_matches = [
            e for e in raw_expenses
            if str(e.get("category", "")).lower() == category.lower()
        ]
        if not cat_matches:
            avail_cats = sorted(list({str(e.get("category")) for e in raw_expenses if e.get("category")}))
            reasons.append(
                f"No records found for category '{category}'" + (f" (available: {', '.join(avail_cats[:5])})" if avail_cats else "")
            )
    elif expense_type == "travel":
        travel_cats = {"flight", "transport", "accommodation", "meals"}
        travel_matches = [
            e for e in raw_expenses
            if str(e.get("category", "")).lower() in travel_cats
        ]
        if not travel_matches:
            avail_cats = sorted(list({str(e.get("category")) for e in raw_expenses if e.get("category")}))
            reasons.append(
                f"No travel expenses found (available categories: {', '.join(avail_cats)})"
            )

    # 4. Location
    if location:
        if not location_supported:
            reasons.append(
                f"Location filtering was requested for '{location}', but the active dataset does not support location data"
            )
        else:
            loc_matches = [
                e for e in raw_expenses
                if location.lower() in str(e.get("location") or e.get("city") or e.get("destination") or "").lower()
            ]
            if not loc_matches:
                avail_locs = sorted(list({str(e.get("location") or e.get("city") or e.get("destination")) for e in raw_expenses if (e.get("location") or e.get("city") or e.get("destination"))}))
                reasons.append(
                    f"No records found for location '{location}'" + (f" (available: {', '.join(avail_locs[:5])})" if avail_locs else "")
                )

    if reasons:
        return "Zero records matched: " + "; ".join(reasons) + "."
    return f"No records matched the combined filter criteria for {expense_type} expenses ({start_date} to {end_date})."


def _append_agent_log(state: AgentState, agent_name: str, message: str) -> list:
    """Helper to append structured agent log."""
    logs = list(state.get("agent_logs") or [])
    logs.append({
        "agent": agent_name,
        "message": message,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    })
    return logs


# ---------------------------------------------------------------------------
# AGENT 1: Expense Analysis Agent
# ---------------------------------------------------------------------------

def expense_analysis_agent_node(state: AgentState) -> dict:
    """
    Agent 1: Expense Analysis Agent.
    
    Responsibilities:
    1. Parse natural-language user request using canonical filters (zero state leakage).
    2. Synchronize active input or retrieve from SQLite persistent memory scoped to dataset.
    3. Normalize location columns and detect location support.
    4. Dynamically discover and filter matching records by date, employee, category, and location.
    5. Provide diagnostic zero-match explanation when zero records match.
    6. Categorize records using rule-based inference.
    7. Emit structured analysis output for downstream agents.
    """
    user_request = state.get("user_request", "").strip()
    status = list(state.get("workflow_status") or [])
    report_run_id = state.get("report_run_id") or f"REP-{uuid.uuid4().hex[:10]}"
    dataset_id = state.get("dataset_id")
    dataset_version = state.get("dataset_version")

    if not user_request:
        return {
            "error": "No request provided. Please enter your expense report request.",
            "workflow_status": ["✗ [Expense Analysis Agent] No request provided."],
            "validation_status": "Needs Human Review",
        }

    # 1. Ingestion & Retrieval from Persistent Memory DB / Active Input
    data_source = "csv_file"
    raw_expenses = []

    try:
        # Check if custom expenses passed in initial state (e.g. from Streamlit editor/uploader)
        if state.get("expenses") and len(state.get("expenses")) > 0:
            raw_expenses = state["expenses"]
            data_source = state.get("data_source", "interactive_editor")
            # Persist to SQLite memory scoped to active dataset
            save_res = save_expenses(
                raw_expenses,
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                source_name="active_session",
            )
            raw_expenses = save_res["records"]
            if not dataset_id:
                dataset_id = save_res.get("dataset_id")
            if dataset_version is None:
                dataset_version = save_res.get("dataset_version")
        elif dataset_id:
            # First check if persistent memory already has records for this dataset
            db_recs = retrieve_expenses_from_db(
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                include_excluded=True,
            )
            if db_recs:
                raw_expenses = db_recs
                data_source = "memory_db"
            else:
                csv_path = os.getenv("EXPENSE_CSV_PATH", "data/expenses.csv")
                loaded = get_expenses(csv_path)
                save_res = save_expenses(
                    loaded,
                    dataset_id=dataset_id,
                    dataset_version=dataset_version,
                    source_name=os.path.basename(csv_path),
                )
                raw_expenses = save_res["records"]
                data_source = "memory_db"
                if not dataset_id:
                    dataset_id = save_res.get("dataset_id")
                if dataset_version is None:
                    dataset_version = save_res.get("dataset_version")
        else:
            # Load from default CSV and persist to memory DB
            csv_path = os.getenv("EXPENSE_CSV_PATH", "data/expenses.csv")
            loaded = get_expenses(csv_path)
            save_res = save_expenses(
                loaded,
                dataset_id=dataset_id,
                dataset_version=dataset_version,
                source_name=os.path.basename(csv_path),
            )
            raw_expenses = save_res["records"]
            data_source = "memory_db"
            if not dataset_id:
                dataset_id = save_res.get("dataset_id")
            if dataset_version is None:
                dataset_version = save_res.get("dataset_version")

        status.append(f"✓ [Expense Analysis Agent] Retrieved {len(raw_expenses)} records from persistent memory ({data_source})")
    except Exception as e:
        status.append(f"✗ [Expense Analysis Agent] Data retrieval failed: {str(e)}")
        return {
            "error": f"Failed to retrieve expense data: {str(e)}",
            "workflow_status": status,
            "validation_status": "Needs Human Review",
        }

    # 2. Location Schema Normalization
    raw_expenses, location_supported = normalize_expense_columns(raw_expenses)

    # 3. Dynamic Employee Discovery from Dataset
    dataset_employees = sorted(list({
        str(exp.get("employee", "")).strip()
        for exp in raw_expenses
        if exp.get("employee") and str(exp.get("employee", "")).strip()
    }))

    # 4. Canonical Intent & Filter Extraction (Zero State Leakage)
    # Target employee is derived strictly from user_request & dataset_employees, NEVER leaked from state
    parsed_filters = extract_canonical_filters(user_request, dataset_employees=dataset_employees)
    start_date = parsed_filters.get("start_date")
    end_date = parsed_filters.get("end_date")
    expense_type = parsed_filters.get("expense_type", "travel")
    time_period = parsed_filters.get("time_period_label")
    target_employee = parsed_filters.get("employee")
    employee_name = target_employee or ""
    category = parsed_filters.get("category")
    location = parsed_filters.get("location")

    time_disp = f" for {time_period}" if time_period and str(time_period).lower() not in ("all", "all dates", "all time") else ""
    emp_disp = f" ({target_employee})" if target_employee else ""
    status.append(f"🤖 [Expense Analysis Agent] Request parsed: {expense_type.title()} expenses{time_disp}{emp_disp}")
    if target_employee:
        status.append(f"✓ [Expense Analysis Agent] Dynamic employee matched: {target_employee}")

    # 5. Filter Expenses Deterministically
    filtered = filter_expenses(
        expenses=raw_expenses,
        start_date=start_date,
        end_date=end_date,
        expense_type=expense_type,
        employee_name=target_employee if target_employee else None,
        category=category,
        location=location,
        location_supported=location_supported,
    )
    filter_match_count = len(filtered)

    # 6. Zero-Match Diagnostic Handling
    if not filtered:
        zero_match_explanation = explain_zero_match(
            raw_expenses=raw_expenses,
            parsed_filters=parsed_filters,
            location_supported=location_supported,
        )
        status.append(f"⚠️ [Expense Analysis Agent] {zero_match_explanation}")
        return {
            "error": zero_match_explanation,
            "filtered_expenses": [],
            "parsed_filters": parsed_filters,
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
            "filter_match_count": 0,
            "zero_match_explanation": zero_match_explanation,
            "location_supported": location_supported,
            "workflow_status": status,
            "validation_status": "Needs Human Review",
        }

    # 7. Categorize Expenses
    categorized = categorize_expenses(filtered)
    status.append(f"✓ [Expense Analysis Agent] Categorized {len(categorized)} relevant expenses")

    unique_emps = sorted(list({
        str(exp.get("employee", "")).strip()
        for exp in categorized
        if exp.get("employee") and str(exp.get("employee", "")).strip()
    }))

    if len(unique_emps) > 1:
        emp_name = "Company Team"
        status.append(f"✓ [Expense Analysis Agent] Multi-person analysis: {len(unique_emps)} employees ({', '.join(unique_emps)})")
    elif len(unique_emps) == 1:
        emp_name = unique_emps[0]
        status.append(f"✓ [Expense Analysis Agent] Single employee analysis: {emp_name}")
    else:
        emp_name = employee_name or "Employee"

    # 8. Structured Output
    expense_analysis = {
        "agent": "Expense Analysis Agent",
        "status": "completed",
        "user_request": user_request,
        "time_period": time_period,
        "start_date": start_date,
        "end_date": end_date,
        "expense_type": expense_type,
        "target_employee": target_employee,
        "employee_name": emp_name,
        "data_source": data_source,
        "total_source_records": len(raw_expenses),
        "selected_records_count": len(categorized),
        "unique_employees": unique_emps,
        "completed_at": datetime.now().isoformat(),
    }

    logs = _append_agent_log(
        state,
        "Expense Analysis Agent",
        f"Filtered {len(categorized)} of {len(raw_expenses)} records for {emp_name} ({start_date} to {end_date})"
    )

    return {
        "report_run_id": report_run_id,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "start_date": start_date,
        "end_date": end_date,
        "expense_type": expense_type,
        "employee_name": emp_name,
        "target_employee": target_employee,
        "parsed_filters": parsed_filters,
        "filter_match_count": filter_match_count,
        "zero_match_explanation": None,
        "location_supported": location_supported,
        "data_source": data_source,
        "expenses": raw_expenses,
        "filtered_expenses": filtered,
        "categorized_expenses": categorized,
        "expense_analysis": expense_analysis,
        "agent_logs": logs,
        "workflow_status": status,
        "error": "",
    }


# ---------------------------------------------------------------------------
# AGENT 2: Validation Agent
# ---------------------------------------------------------------------------

def validation_agent_node(state: AgentState) -> dict:
    """
    Agent 2: Validation Agent.
    
    Responsibilities:
    1. Consume structured output from Expense Analysis Agent.
    2. Audit transactions against validation rules (receipts, amounts, duplicates).
    3. Persist identified issues into SQLite memory.
    4. Determine whether Human-in-the-Loop review is required.
    """
    categorized = state.get("categorized_expenses") or []
    status = list(state.get("workflow_status") or [])

    if state.get("error") and not categorized:
        status.append("🤖 [Validation Agent] Analysis produced error or zero records; audit skipped.")
        return {"workflow_status": status}

    status.append("🤖 [Validation Agent] Commencing compliance & transaction audit...")

    # Validate all transactions
    issues = validate_expenses(categorized)

    # Persist issues to SQLite memory scoped to dataset_id and version
    saved_issues = save_validation_issues(
        issues,
        dataset_id=state.get("dataset_id"),
        dataset_version=state.get("dataset_version"),
    )

    # 1. Classify saved issues from persistent memory
    unresolved_issues = [
        iss for iss in saved_issues
        if iss.get("status") == "unresolved"
    ]
    accepted_exceptions = [
        iss for iss in saved_issues
        if iss.get("status") == "accepted_exception" or iss.get("reviewer_decision") == "accept_exception"
    ]
    excluded_issues = [
        iss for iss in saved_issues
        if iss.get("status") == "excluded" or iss.get("reviewer_decision") in ("exclude", "exclude_single", "excluded")
    ]

    # 2. Filter out pre-excluded transactions from categorized expenses
    excluded_ids = {iss.get("record_id") or iss.get("expense_record_id") for iss in excluded_issues}
    for exp in categorized:
        if exp.get("is_excluded") in (1, True, "1", "true"):
            excluded_ids.add(exp.get("record_id"))

    if excluded_ids:
        categorized = [
            exp for exp in categorized
            if (exp.get("record_id") not in excluded_ids and exp.get("is_excluded") not in (1, True, "1", "true"))
        ]
        unresolved_issues = [
            iss for iss in unresolved_issues
            if (iss.get("record_id") not in excluded_ids and iss.get("expense_record_id") not in excluded_ids)
        ]
        status.append(f"✓ [Validation Agent] Omitted {len(excluded_ids)} pre-excluded record(s) from report.")

    # 3. Synchronize persistent reviewer decisions into state
    human_decisions = list(state.get("human_decisions") or [])
    for exc in accepted_exceptions:
        rec_id = exc.get("record_id") or exc.get("expense_record_id")
        notes = exc.get("reviewer_notes") or f"Pre-authorized managerial exception for {rec_id}"
        if not any(d.get("record_id") == rec_id for d in human_decisions):
            human_decisions.append({
                "action": "accepted_exception",
                "record_id": rec_id,
                "accepted_count": 1,
                "reason": notes,
                "notes": notes,
                "timestamp": datetime.now().isoformat(),
            })

    for exc in excluded_issues:
        rec_id = exc.get("record_id") or exc.get("expense_record_id")
        if not any(d.get("record_id") == rec_id for d in human_decisions):
            human_decisions.append({
                "action": "exclude_single",
                "record_id": rec_id,
                "timestamp": datetime.now().isoformat(),
            })

    # 4. Determine if Human-in-the-Loop review is required
    requires_review = len(unresolved_issues) > 0
    if requires_review:
        val_status = "Needs Human Review"
        status.append(f"⚠️ [Validation Agent] Flagged {len(unresolved_issues)} issue(s) requiring human review.")
    elif accepted_exceptions:
        val_status = "Reviewed with Exceptions"
        status.append(f"✓ [Validation Agent] {len(accepted_exceptions)} exception(s) pre-authorized in persistent memory. Proceeding without interruption.")
    else:
        val_status = "Clear"
        status.append("✓ [Validation Agent] Zero validation discrepancies found. Clean bill of health.")

    validation_findings = {
        "agent": "Validation Agent",
        "status": "completed",
        "total_issues": len(saved_issues),
        "unresolved_count": len(unresolved_issues),
        "accepted_exceptions_count": len(accepted_exceptions),
        "requires_human_review": requires_review,
        "issues": saved_issues,
        "audit_timestamp": datetime.now().isoformat(),
    }

    logs = _append_agent_log(
        state,
        "Validation Agent",
        f"Audit completed: {len(unresolved_issues)} unresolved issues, {len(accepted_exceptions)} pre-authorized exceptions. Status: {val_status}"
    )

    return {
        "categorized_expenses": categorized,
        "missing_data": unresolved_issues,
        "validation_findings": saved_issues,
        "unresolved_count": len(unresolved_issues),
        "validation_status": val_status,
        "awaiting_input": "missing_data" if requires_review else "",
        "human_decisions": human_decisions,
        "agent_logs": logs,
        "workflow_status": status,
    }


# ---------------------------------------------------------------------------
# Human-in-the-Loop Review Node & Revalidation Node
# ---------------------------------------------------------------------------

def human_review_node(state: AgentState) -> dict:
    """
    Human-in-the-Loop Review Node.
    
    Suspends execution via LangGraph interrupt() when discrepancies are flagged.
    Handles reviewer decisions:
    - 'exclude': strips flagged records, records exclusion in audit trail.
    - 'include' / 'accept_exceptions': documents exception, marks status 'Reviewed with Exceptions'.
    - dict with action 'correct': updates record in SQLite memory and queues revalidation.
    """
    missing = state.get("missing_data") or []
    status = list(state.get("workflow_status") or [])

    if not missing:
        return {"awaiting_input": "", "validation_status": "Clear"}

    issue_summary = "\n".join(
        f"  • {m.get('message', 'Issue')}" for m in missing
    )

    user_response = interrupt({
        "question": (
            f"⚠️ Found {len(missing)} issue(s) requiring review:\n{issue_summary}\n\n"
            "How would you like to proceed?\n"
            "• Include / Accept — Proceed with documented managerial exceptions\n"
            "• Exclude — Remove flagged expenses from this report\n"
            "• Correct — Provide field corrections"
        ),
        "options": ["include", "exclude", "correct"],
        "issues": missing,
        "type": "missing_data",
    })

    human_decisions = list(state.get("human_decisions") or [])
    resp_str = str(user_response).lower().strip()

    # Case 0: Exclude single record
    if isinstance(user_response, dict) and user_response.get("action") == "exclude_single":
        rec_id = user_response.get("record_id")
        categorized = state.get("categorized_expenses") or []
        cleaned = [exp for exp in categorized if exp.get("record_id") != rec_id]

        apply_reviewer_decision(
            action="exclude",
            record_id=rec_id,
            dataset_id=state.get("dataset_id"),
            dataset_version=state.get("dataset_version"),
            reason="Excluded by reviewer during HITL review",
        )

        for m in missing:
            if m.get("record_id") == rec_id:
                issue_id = m.get("issue_id")
                if issue_id:
                    resolve_validation_issue(issue_id, decision="excluded", notes="Excluded by reviewer during HITL review")

        remaining_missing = [m for m in missing if m.get("record_id") != rec_id]
        human_decisions.append({
            "action": "exclude_single",
            "record_id": rec_id,
            "timestamp": datetime.now().isoformat(),
        })
        status.append(f"✓ [Human Review] Excluded record {rec_id} from counting and report.")
        logs = _append_agent_log(state, "Human Review", f"Excluded record {rec_id} from calculations.")

        val_status = "Clear" if len(remaining_missing) == 0 else "Needs Human Review"
        awaiting = "" if len(remaining_missing) == 0 else "missing_data"

        return {
            "categorized_expenses": cleaned,
            "missing_data": remaining_missing,
            "unresolved_count": len(remaining_missing),
            "human_response": "exclude_single",
            "human_decisions": human_decisions,
            "validation_status": val_status,
            "awaiting_input": awaiting,
            "workflow_status": status,
            "agent_logs": logs,
        }

    # Case 0B: Accept single record exception
    if isinstance(user_response, dict) and user_response.get("action") in ("accept_single", "accept_exception"):
        rec_id = user_response.get("record_id")
        reason = user_response.get("reason", "Authorized managerial exception approved during HITL review")

        apply_reviewer_decision(
            action="accept_exception",
            record_id=rec_id,
            dataset_id=state.get("dataset_id"),
            dataset_version=state.get("dataset_version"),
            reason=reason,
        )

        for m in missing:
            if m.get("record_id") == rec_id:
                issue_id = m.get("issue_id")
                if issue_id:
                    resolve_validation_issue(issue_id, decision="accepted_exception", notes=reason)

        remaining_missing = [m for m in missing if m.get("record_id") != rec_id]
        human_decisions.append({
            "action": "accepted_exception",
            "record_id": rec_id,
            "accepted_count": 1,
            "reason": reason,
            "notes": reason,
            "timestamp": datetime.now().isoformat(),
        })
        status.append(f"✓ [Human Review] Authorized managerial exception for record {rec_id}.")
        logs = _append_agent_log(state, "Human Review", f"Authorized managerial exception for {rec_id}.")

        val_status = "Reviewed with Exceptions" if len(remaining_missing) == 0 else "Needs Human Review"
        awaiting = "" if len(remaining_missing) == 0 else "missing_data"

        return {
            "missing_data": remaining_missing,
            "unresolved_count": len(remaining_missing),
            "human_response": "accept_single",
            "human_decisions": human_decisions,
            "validation_status": val_status,
            "awaiting_input": awaiting,
            "workflow_status": status,
            "agent_logs": logs,
        }

    # Case 1: Exclude all flagged records
    if "exclude" in resp_str:
        flagged_rec_ids = {m.get("record_id") for m in missing if m.get("record_id")}
        categorized = state.get("categorized_expenses") or []
        cleaned = [
            exp for exp in categorized
            if exp.get("record_id") not in flagged_rec_ids
        ]

        for rid in flagged_rec_ids:
            apply_reviewer_decision(
                action="exclude",
                record_id=rid,
                dataset_id=state.get("dataset_id"),
                dataset_version=state.get("dataset_version"),
                reason="Excluded by reviewer during HITL review",
            )

        for m in missing:
            issue_id = m.get("issue_id")
            if issue_id:
                resolve_validation_issue(issue_id, decision="excluded", notes="Excluded by reviewer during HITL review")

        decision_entry = {
            "action": "exclude",
            "excluded_count": len(flagged_rec_ids),
            "timestamp": datetime.now().isoformat(),
        }
        human_decisions.append(decision_entry)
        status.append(f"✓ [Human Review] Reviewer excluded {len(flagged_rec_ids)} flagged transaction(s)")

        logs = _append_agent_log(state, "Human Review", f"Excluded {len(flagged_rec_ids)} transactions from report.")

        return {
            "categorized_expenses": cleaned,
            "missing_data": [],
            "unresolved_count": 0,
            "human_response": "exclude",
            "human_decisions": human_decisions,
            "validation_status": "Clear",
            "awaiting_input": "",
            "workflow_status": status,
            "agent_logs": logs,
        }

    # Case 2: Correction passed via dict or JSON
    elif isinstance(user_response, dict) and user_response.get("action") == "correct":
        rec_id = user_response.get("record_id")
        updates = user_response.get("updates", {})

        if rec_id and updates:
            update_expense_record(
                rec_id,
                updates,
                dataset_id=state.get("dataset_id"),
                dataset_version=state.get("dataset_version"),
            )
            # Update in active categorized list
            categorized = state.get("categorized_expenses") or []
            for exp in categorized:
                if exp.get("record_id") == rec_id:
                    exp.update(updates)

            human_decisions.append({
                "action": "correct",
                "record_id": rec_id,
                "updates": updates,
                "timestamp": datetime.now().isoformat(),
            })
            status.append(f"✓ [Human Review] Applied corrections to record {rec_id}. Revalidating...")

        return {
            "human_response": "correct",
            "human_decisions": human_decisions,
            "awaiting_input": "",
            "workflow_status": status,
        }

    # Case 3: Accept exceptions / Include
    else:
        for m in missing:
            rid = m.get("record_id")
            if rid:
                apply_reviewer_decision(
                    action="accept_exception",
                    record_id=rid,
                    dataset_id=state.get("dataset_id"),
                    dataset_version=state.get("dataset_version"),
                    reason="Authorized exception accepted by reviewer during HITL review",
                )
            issue_id = m.get("issue_id")
            if issue_id:
                resolve_validation_issue(
                    issue_id,
                    decision="accepted_exception",
                    notes="Authorized exception accepted by reviewer during HITL review",
                )

        decision_entry = {
            "action": "accepted_exception",
            "accepted_count": len(missing),
            "timestamp": datetime.now().isoformat(),
        }
        human_decisions.append(decision_entry)
        status.append(f"✓ [Human Review] Reviewer accepted {len(missing)} item(s) as documented exceptions.")

        logs = _append_agent_log(state, "Human Review", f"Accepted {len(missing)} exceptions under policy.")

        return {
            "human_response": "include",
            "human_decisions": human_decisions,
            "validation_status": "Reviewed with Exceptions",
            "awaiting_input": "",
            "workflow_status": status,
            "agent_logs": logs,
        }


def revalidation_node(state: AgentState) -> dict:
    """
    Revalidates records following a reviewer correction.
    If all issues are resolved, marks status 'Clear'.
    """
    categorized = state.get("categorized_expenses") or []
    status = list(state.get("workflow_status") or [])
    remaining_issues = validate_expenses(categorized)

    if not remaining_issues:
        status.append("✓ [Validation Agent] Revalidation passed! All corrections verified.")
        return {
            "missing_data": [],
            "validation_findings": [],
            "unresolved_count": 0,
            "validation_status": "Clear",
            "awaiting_input": "",
            "workflow_status": status,
        }
    else:
        status.append(f"⚠️ [Validation Agent] Revalidation found {len(remaining_issues)} remaining issue(s).")
        return {
            "missing_data": remaining_issues,
            "validation_findings": remaining_issues,
            "unresolved_count": len(remaining_issues),
            "validation_status": "Needs Human Review",
            "awaiting_input": "missing_data",
            "workflow_status": status,
        }


# ---------------------------------------------------------------------------
# AGENT 3: Report Generation Agent
# ---------------------------------------------------------------------------

def report_generation_agent_node(state: AgentState) -> dict:
    """
    Agent 3: Report Generation Agent.
    
    Responsibilities:
    1. Verify audit status: never silently approve unresolved issues.
    2. Compute deterministic financial totals (Pandas).
    3. Generate publication-grade PDF report (ReportLab) with validation status banner.
    4. Persist report run metadata into SQLite memory.
    5. Emit structured report payload.
    """
    if state.get("error"):
        return {}

    val_status = state.get("validation_status", "Clear")
    unresolved_count = state.get("unresolved_count", 0)

    # Integrity guard: Unresolved issues must NEVER be treated as approved
    if val_status == "Needs Human Review" and unresolved_count > 0:
        return {
            "error": f"Cannot generate final approved report: {unresolved_count} unresolved validation issue(s) remain.",
            "workflow_status": list(state.get("workflow_status") or []) + [
                "✗ [Report Generation Agent] Aborted: Unresolved compliance issues cannot be silently approved."
            ],
        }

    categorized = state.get("categorized_expenses") or []
    status = list(state.get("workflow_status") or [])
    status.append("🤖 [Report Generation Agent] Calculating deterministic totals and preparing PDF report...")

    # 1. Deterministic Financial Math via Pandas
    totals = calculate_totals(categorized)
    grand_total = totals.get("grand_total", 0.0)

    # 2. Extract exception notes if any
    human_decisions = state.get("human_decisions") or []
    validation_notes = []
    for d in human_decisions:
        if d.get("action") == "accepted_exception":
            validation_notes.append(f"Managerial Exception: Accepted {d.get('accepted_count', 0)} item(s) without original receipt.")
        elif d.get("action") == "exclude":
            validation_notes.append(f"Excluded {d.get('excluded_count', 0)} non-compliant transaction(s).")

    report_run_id = state.get("report_run_id") or f"REP-{uuid.uuid4().hex[:10]}"
    employee_name = state.get("employee_name", "Employee")
    start_date = state.get("start_date", "")
    end_date = state.get("end_date", "")

    # 3. Generate ReportLab PDF Report
    try:
        pdf_path = generate_pdf(
            expenses=categorized,
            totals=totals,
            missing_data=state.get("missing_data") or [],
            employee_name=employee_name,
            start_date=start_date,
            end_date=end_date,
            validation_status=val_status,
            validation_notes=validation_notes,
            report_id=report_run_id,
        )
        status.append(f"✓ [Report Generation Agent] Generated PDF Report: {os.path.basename(pdf_path)}")
    except Exception as e:
        status.append(f"✗ [Report Generation Agent] PDF generation failed: {str(e)}")
        return {
            "error": f"PDF generation failed: {str(e)}",
            "workflow_status": status,
        }

    # 4. Persist Report Run in SQLite Persistent Memory
    report_record = {
        "report_id": report_run_id,
        "user_request": state.get("user_request", ""),
        "filters": state.get("parsed_filters") or {
            "start_date": start_date,
            "end_date": end_date,
            "expense_type": state.get("expense_type", "travel"),
            "employee_name": employee_name,
        },
        "transaction_ids": [exp.get("record_id") for exp in categorized if exp.get("record_id")],
        "transaction_count": totals.get("transaction_count", len(categorized)),
        "grand_total": grand_total,
        "validation_status": val_status,
        "report_file_path": pdf_path,
        "human_review_status": "Completed" if human_decisions else "Not Required",
    }
    save_report_run(
        report_record,
        dataset_id=state.get("dataset_id"),
        dataset_version=state.get("dataset_version"),
    )
    status.append(f"✓ [Report Generation Agent] Persisted report run {report_run_id} to SQLite memory.")

    report_payload = {
        "agent": "Report Generation Agent",
        "status": "completed",
        "report_run_id": report_run_id,
        "dataset_id": state.get("dataset_id"),
        "dataset_version": state.get("dataset_version"),
        "parsed_filters": state.get("parsed_filters"),
        "grand_total": grand_total,
        "transaction_count": totals.get("transaction_count", 0),
        "validation_status": val_status,
        "pdf_path": pdf_path,
        "completed_at": datetime.now().isoformat(),
    }

    logs = _append_agent_log(
        state,
        "Report Generation Agent",
        f"Generated {os.path.basename(pdf_path)} with total ₹{grand_total:,.2f} (Status: {val_status})"
    )

    return {
        "totals": totals,
        "pdf_path": pdf_path,
        "report_payload": report_payload,
        "agent_logs": logs,
        "workflow_status": status,
    }


def complete_node(state: AgentState) -> dict:
    """Final wrap-up node summarizing multi-agent workflow results."""
    status = list(state.get("workflow_status") or [])
    totals = state.get("totals") or {}
    grand_total = totals.get("grand_total", 0.0)
    val_status = state.get("validation_status", "Clear")

    if state.get("error"):
        status.append(f"✗ Workflow ended with notice: {state['error']}")
    else:
        status.append(
            f"🎉 [Workflow Complete] Multi-agent execution succeeded! "
            f"Grand Total: ₹{grand_total:,.2f} | Status: {val_status}"
        )

    return {"workflow_status": status}


# ---------------------------------------------------------------------------
# Routing Functions
# ---------------------------------------------------------------------------

def route_after_analysis(state: AgentState) -> str:
    """Route after Agent 1: proceed to Validation Agent or skip if error."""
    if state.get("error"):
        return "complete"
    return "validation_agent"


def route_after_validation(state: AgentState) -> str:
    """Route after Agent 2: if discrepancies found, interrupt for human review."""
    if state.get("error"):
        return "complete"
    if state.get("awaiting_input") == "missing_data":
        return "human_review_node"
    return "report_generation_agent"


def route_after_human_review(state: AgentState) -> str:
    """Route after Human Review: if correction made, revalidate; otherwise proceed."""
    if state.get("error"):
        return "complete"
    if state.get("awaiting_input") == "missing_data":
        return "human_review_node"
    if state.get("human_response") == "correct":
        return "revalidation_node"
    return "report_generation_agent"


def route_after_revalidation(state: AgentState) -> str:
    """Route after Revalidation: if still unresolved, re-interrupt, else proceed."""
    if state.get("awaiting_input") == "missing_data":
        return "human_review_node"
    return "report_generation_agent"


# ---------------------------------------------------------------------------
# Build & Compile Graph
# ---------------------------------------------------------------------------

def build_agent_graph():
    """
    Construct the LangGraph StateGraph connecting the three collaborating agents,
    HITL review, and memory persistence.
    """
    builder = StateGraph(AgentState)

    # 1. Add Nodes
    builder.add_node("expense_analysis_agent", expense_analysis_agent_node)
    builder.add_node("validation_agent", validation_agent_node)
    builder.add_node("human_review_node", human_review_node)
    builder.add_node("revalidation_node", revalidation_node)
    builder.add_node("report_generation_agent", report_generation_agent_node)
    builder.add_node("complete", complete_node)

    # 2. Add Edges & Conditional Routing
    builder.add_edge(START, "expense_analysis_agent")
    
    builder.add_conditional_edges(
        "expense_analysis_agent",
        route_after_analysis,
        {
            "validation_agent": "validation_agent",
            "complete": "complete",
        },
    )
    
    builder.add_conditional_edges(
        "validation_agent",
        route_after_validation,
        {
            "human_review_node": "human_review_node",
            "report_generation_agent": "report_generation_agent",
            "complete": "complete",
        },
    )
    
    builder.add_conditional_edges(
        "human_review_node",
        route_after_human_review,
        {
            "human_review_node": "human_review_node",
            "revalidation_node": "revalidation_node",
            "report_generation_agent": "report_generation_agent",
            "complete": "complete",
        },
    )
    
    builder.add_conditional_edges(
        "revalidation_node",
        route_after_revalidation,
        {
            "human_review_node": "human_review_node",
            "report_generation_agent": "report_generation_agent",
        },
    )
    
    builder.add_edge("report_generation_agent", "complete")
    builder.add_edge("complete", END)

    return builder


def get_compiled_graph():
    """
    Return a compiled LangGraph with SQLite checkpointer for state persistence.
    Workflow checkpoints are kept in .checkpoints/agent_state.db (or AGENT_CHECKPOINT_DB_PATH).
    """
    import sqlite3

    builder = build_agent_graph()

    checkpoint_path = os.getenv("AGENT_CHECKPOINT_DB_PATH", os.path.join(".checkpoints", "agent_state.db"))
    checkpoint_dir = os.path.dirname(checkpoint_path)
    if checkpoint_dir:
        os.makedirs(checkpoint_dir, exist_ok=True)
    conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    return builder.compile(checkpointer=checkpointer), checkpointer
