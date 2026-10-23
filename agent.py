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

from state import AgentState
from tools.expense_tools import get_expenses, filter_expenses
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
                return json.loads(json_match.group())
        except Exception:
            pass

    return _regex_extract_intent(user_request)


def _regex_extract_intent(user_request: str) -> dict:
    """Regex-based fallback for intent extraction."""
    request_lower = user_request.lower()

    # Normalize common typos
    req_clean = request_lower.replace("augest", "august").replace("aprl", "april")

    # Expense type
    expense_type = "travel"
    if "all" in req_clean and "expense" in req_clean:
        expense_type = "all"

    # Time period
    time_period = "last month"
    month_match = re.search(
        r'(january|february|march|april|may|june|july|august|september|october|november|december)\s*(\d{4})?',
        req_clean,
    )
    if month_match:
        time_period = month_match.group(0).strip()
    elif "last month" in req_clean:
        time_period = "last month"
    elif "this month" in req_clean:
        time_period = "this month"

    # Dynamic employee extraction from prompt (zero hardcoding)
    employee_name = ""
    match_for = re.search(r'\b(?:for|of)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)\b', user_request)
    if match_for:
        candidate = match_for.group(1).strip()
        ignore_words = {
            "last", "this", "next", "month", "year",
            "january", "february", "march", "april", "may", "june",
            "july", "august", "augest", "september", "october", "november", "december",
            "finance", "manager", "hr", "company", "travel", "all", "expenses", "expense",
            "someone", "person", "team", "everyone", "my", "our", "me", "report"
        }
        words = candidate.lower().split()
        if not any(w in ignore_words for w in words):
            employee_name = candidate.title()

    return {
        "expense_type": expense_type,
        "time_period": time_period,
        "employee_name": employee_name,
    }


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
    1. Parse natural-language user request (LLM / regex fallback).
    2. Synchronize active input or retrieve from SQLite persistent memory.
    3. Dynamically discover and filter matching records by date, employee, and type.
    4. Categorize records using rule-based inference.
    5. Emit structured analysis output for downstream agents.
    """
    user_request = state.get("user_request", "").strip()
    status = list(state.get("workflow_status") or [])
    report_run_id = state.get("report_run_id") or f"REP-{uuid.uuid4().hex[:10]}"

    if not user_request:
        return {
            "error": "No request provided. Please enter your expense report request.",
            "workflow_status": ["✗ [Expense Analysis Agent] No request provided."],
            "validation_status": "Needs Human Review",
        }

    # 1. Parse Intent & Dates
    intent = _llm_extract_intent(user_request)
    time_period = intent.get("time_period", "last month")
    start_date, end_date = _resolve_date_range(time_period)
    expense_type = intent.get("expense_type", "travel")
    target_employee = intent.get("employee_name", "").strip()
    employee_name = target_employee if target_employee else state.get("employee_name", "").strip()

    status.append(f"🤖 [Expense Analysis Agent] Request parsed: {expense_type.title()} expenses for {time_period}")

    # 2. Ingestion & Retrieval from Persistent Memory DB
    data_source = "csv_file"
    raw_expenses = []

    try:
        # Check if custom expenses passed in initial state (e.g. from Streamlit editor/uploader)
        if state.get("expenses") and len(state.get("expenses")) > 0:
            raw_expenses = state["expenses"]
            data_source = state.get("data_source", "interactive_editor")
            # Persist to SQLite memory
            save_res = save_expenses(raw_expenses, source_name="active_session")
            raw_expenses = save_res["records"]
        else:
            # Load from default CSV and persist to memory DB
            csv_path = os.getenv("EXPENSE_CSV_PATH", "data/expenses.csv")
            loaded = get_expenses(csv_path)
            save_res = save_expenses(loaded, source_name=os.path.basename(csv_path))
            raw_expenses = save_res["records"]
            data_source = "memory_db"

        status.append(f"✓ [Expense Analysis Agent] Retrieved {len(raw_expenses)} records from persistent memory ({data_source})")
    except Exception as e:
        status.append(f"✗ [Expense Analysis Agent] Data retrieval failed: {str(e)}")
        return {
            "error": f"Failed to retrieve expense data: {str(e)}",
            "workflow_status": status,
            "validation_status": "Needs Human Review",
        }

    # 3. Dynamic Employee Discovery
    dataset_employees = sorted(list({
        str(exp.get("employee", "")).strip()
        for exp in raw_expenses
        if exp.get("employee") and str(exp.get("employee", "")).strip()
    }))

    user_req_lower = user_request.lower()
    if not target_employee:
        for de in dataset_employees:
            if de.lower() in user_req_lower:
                target_employee = de
                employee_name = de
                status.append(f"✓ [Expense Analysis Agent] Dynamic employee matched: {de}")
                break
            first_name = de.split()[0].lower()
            if len(first_name) >= 3 and re.search(r'\b' + re.escape(first_name) + r'\b', user_req_lower):
                target_employee = de
                employee_name = de
                status.append(f"✓ [Expense Analysis Agent] Dynamic employee matched: {de}")
                break
    elif target_employee:
        for de in dataset_employees:
            if de.lower() == target_employee.lower() or target_employee.lower() in de.lower():
                target_employee = de
                employee_name = de
                break

    # 4. Filter Expenses Deterministically
    filtered = filter_expenses(
        expenses=raw_expenses,
        start_date=start_date,
        end_date=end_date,
        expense_type=expense_type,
        employee_name=target_employee if target_employee else None,
    )

    if not filtered:
        emp_msg = f" for {target_employee}" if target_employee else ""
        err_msg = f"No {expense_type} expenses found{emp_msg} between {start_date} and {end_date}."
        status.append(f"⚠ [Expense Analysis Agent] {err_msg}")
        return {
            "error": err_msg,
            "filtered_expenses": [],
            "workflow_status": status,
            "validation_status": "Needs Human Review",
        }

    # 5. Categorize Expenses
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

    # 6. Structured Output
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
        "start_date": start_date,
        "end_date": end_date,
        "expense_type": expense_type,
        "employee_name": emp_name,
        "target_employee": target_employee,
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
    if state.get("error"):
        return {}

    categorized = state.get("categorized_expenses") or []
    status = list(state.get("workflow_status") or [])
    status.append("🤖 [Validation Agent] Commencing compliance & transaction audit...")

    # Validate all transactions
    issues = validate_expenses(categorized)

    # Persist issues to SQLite memory
    saved_issues = save_validation_issues(issues)

    requires_review = len(issues) > 0
    val_status = "Needs Human Review" if requires_review else "Clear"

    if requires_review:
        status.append(f"⚠ [Validation Agent] Flagged {len(issues)} issue(s) requiring human review.")
    else:
        status.append("✓ [Validation Agent] Zero validation discrepancies found. Clean bill of health.")

    validation_findings = {
        "agent": "Validation Agent",
        "status": "completed",
        "total_issues": len(issues),
        "requires_human_review": requires_review,
        "issues": saved_issues,
        "audit_timestamp": datetime.now().isoformat(),
    }

    logs = _append_agent_log(
        state,
        "Validation Agent",
        f"Audit completed: {len(issues)} issues detected. Status: {val_status}"
    )

    return {
        "missing_data": issues,
        "validation_findings": issues,
        "unresolved_count": len(issues),
        "validation_status": val_status,
        "awaiting_input": "missing_data" if requires_review else "",
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

    # Case 1: Exclude flagged records
    if "exclude" in resp_str:
        flagged_rec_ids = {m.get("record_id") for m in missing if m.get("record_id")}
        categorized = state.get("categorized_expenses") or []
        cleaned = [
            exp for exp in categorized
            if exp.get("record_id") not in flagged_rec_ids
        ]

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
            update_expense_record(rec_id, updates)
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
        status.append(f"⚠ [Validation Agent] Revalidation found {len(remaining_issues)} remaining issue(s).")
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
        "filters": {
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
    save_report_run(report_record)
    status.append(f"✓ [Report Generation Agent] Persisted report run {report_run_id} to SQLite memory.")

    report_payload = {
        "agent": "Report Generation Agent",
        "status": "completed",
        "report_run_id": report_run_id,
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
    Workflow checkpoints are kept in .checkpoints/agent_state.db.
    """
    import sqlite3

    builder = build_agent_graph()

    os.makedirs(".checkpoints", exist_ok=True)
    conn = sqlite3.connect(".checkpoints/agent_state.db", check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    return builder.compile(checkpointer=checkpointer), checkpointer
