"""
AI Expense Report Agent — Modern FinTech Streamlit Application.

Enterprise-grade user interface for the LangGraph multi-agent expense reporting
and compliance auditing system with persistent SQLite memory.

Features:
- Professional Executive Financial Dashboard
- Multi-Agent Orchestration Tracker (Expense Analysis, Validation, Report Generation)
- Human-in-the-Loop Review Console (Exceptions, Exclusions, Inline Corrections)
- Persistent SQLite Memory & Cryptographic Batch Ingestion Console
- Searchable Historical Prompt & Report Run Repository
- Compliance & Discrepancy Audit Management
- AI-Driven Executive Email Drafting (Qwen 3 / Ollama) & Dispatch (Resend API)
"""

import os
import re
import uuid
import json
import math
import hashlib
from datetime import datetime
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from langgraph.types import Command
from langgraph.errors import GraphInterrupt

# Load environment variables
load_dotenv(override=True)

# Application Tools
from tools.expense_tools import get_expenses
from tools.calculation_tools import calculate_totals
from tools.email_tools import generate_email_draft, send_email_report
from tools.memory_tools import (
    init_memory_db,
    save_expenses,
    retrieve_expenses_from_db,
    get_report_history,
    get_memory_stats,
    get_unresolved_issues,
    resolve_validation_issue,
    update_expense_record,
    get_connection,
    DEFAULT_MEMORY_DB_PATH,
    create_or_get_dataset,
    set_active_dataset,
    get_active_dataset,
    list_datasets,
    get_dataset,
    increment_dataset_version,
    apply_reviewer_decision,
    get_audit_events,
)


def _clean_editor_records(records: list) -> list:
    """Sanitize interactive records from st.data_editor, strictly preserving nulls per R3."""
    cleaned = []
    for r in records:
        # Check if entire row is blank (e.g. newly added row in st.data_editor)
        non_empty = [
            v for v in r.values()
            if v is not None and not (isinstance(v, float) and math.isnan(v)) and str(v).strip() not in ("", "None", "nan", "<NA>", "NoneType")
        ]
        if not non_empty:
            continue

        cr = dict(r)
        # Record ID
        rec_id = cr.get("record_id")
        if rec_id and str(rec_id).strip() not in ("", "None", "nan", "<NA>"):
            cr["record_id"] = str(rec_id).strip()

        # Date: preserve None for missing / null dates without empty string coercion
        d = cr.get("date") if cr.get("date") is not None else cr.get("expense_date")
        if d is None or (isinstance(d, float) and math.isnan(d)) or str(d).strip().lower() in ("nan", "none", "nat", "null", "<na>", ""):
            cr["date"] = None
        else:
            cr["date"] = str(d).split("T")[0].strip()

        # Amount: preserve None for missing / null / NaN amounts (R3); do NOT coerce to 0.0
        amt_raw = cr.get("amount")
        if amt_raw is None or (isinstance(amt_raw, float) and (math.isnan(amt_raw) or math.isinf(amt_raw))) or str(amt_raw).strip().lower() in ("nan", "none", "null", "<na>", ""):
            cr["amount"] = None
        else:
            try:
                s = str(amt_raw).replace("₹", "").replace("$", "").replace(",", "").strip()
                f_val = float(s)
                cr["amount"] = None if (math.isnan(f_val) or math.isinf(f_val)) else f_val
            except (ValueError, TypeError):
                cr["amount"] = None

        # Text fields
        for field in ("employee", "description", "merchant", "category", "receipt_status"):
            val = cr.get(field)
            if val is None or (isinstance(val, float) and math.isnan(val)) or str(val).strip().lower() in ("nan", "none", "null", "<na>"):
                cr[field] = "" if field != "receipt_status" else "Missing"
            else:
                cr[field] = str(val).strip()

        # Location field
        loc_val = None
        for loc_k in ("location", "city", "destination"):
            if loc_k in cr and cr[loc_k] is not None and str(cr[loc_k]).strip() not in ("", "nan", "none", "null", "<NA>"):
                loc_val = str(cr[loc_k]).strip()
                break
        cr["location"] = loc_val

        cleaned.append(cr)
    return cleaned


def ensure_active_dataset() -> dict:
    """Ensure there is an active dataset in SQLite persistent memory. If none, initialize master dataset."""
    init_memory_db()
    active = get_active_dataset()
    if active:
        return active

    # If legacy dataset exists with records, activate it without inserting duplicate records
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM datasets WHERE dataset_id = ?", ("DATASET-LEGACY-UNASSIGNED",)).fetchone()
        if row and row["row_count"] > 0:
            set_active_dataset("DATASET-LEGACY-UNASSIGNED")
            act = get_active_dataset()
            if act:
                return act
    finally:
        conn.close()

    csv_path = os.getenv("EXPENSE_CSV_PATH", "data/expenses.csv")
    try:
        raw_bytes = open(csv_path, "rb").read() if os.path.exists(csv_path) else b"date,employee\n"
        file_hash = hashlib.sha256(raw_bytes).hexdigest()
        df = pd.read_csv(csv_path) if os.path.exists(csv_path) else pd.DataFrame()
        records = _clean_editor_records(df.to_dict(orient="records"))
        ds = create_or_get_dataset(
            name="Master Organization Expenses (expenses.csv)",
            file_hash=file_hash,
            row_count=len(records),
            schema={"columns": list(df.columns)},
        )
        set_active_dataset(ds["dataset_id"])
        save_expenses(
            expenses=records,
            dataset_id=ds["dataset_id"],
            dataset_version=1,
            source_name="expenses.csv",
        )
        return ds
    except Exception:
        return {
            "dataset_id": "DATASET-LEGACY-UNASSIGNED",
            "name": "Legacy Ingested Data",
            "file_hash": "legacy",
            "row_count": 0,
            "version": 1,
            "is_active": 1,
        }

# --- Page Configuration ---
st.set_page_config(
    page_title="AI Expense Report Agent | Enterprise FinTech",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Design System & Modern FinTech Styles ---
st.markdown("""
<style>
    /* Global Typography & Palette */
    :root {
        --brand-primary: #1a237e;
        --brand-primary-dark: #0f172a;
        --brand-accent: #2563eb;
        --surface-canvas: #f8fafc;
        --surface-card: #ffffff;
        --border-subtle: #e2e8f0;
        --border-focus: #94a3b8;
        --text-main: #0f172a;
        --text-muted: #64748b;
        --success-text: #059669;
        --success-bg: #ecfdf5;
        --success-border: #a7f3d0;
        --warning-text: #d97706;
        --warning-bg: #fffbeb;
        --warning-border: #fde68a;
        --error-text: #dc2626;
        --error-bg: #fef2f2;
        --error-border: #fecaca;
        --info-text: #2563eb;
        --info-bg: #eff6ff;
        --info-border: #bfdbfe;
    }

    /* Tabular Numerals for Finance */
    body, [data-testid="stMetricValue"], .fin-number {
        font-feature-settings: "tnum" 1;
        font-variant-numeric: tabular-nums;
    }

    /* Main Container Padding */
    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 3rem;
        max-width: 1200px;
    }

    /* Hero Header Card */
    .hero-header {
        background: linear-gradient(135deg, #0f172a 0%, #1a237e 55%, #1e3a8a 100%);
        border-radius: 14px;
        padding: 1.75rem 2.25rem;
        color: #ffffff;
        margin-bottom: 1.5rem;
        box-shadow: 0 4px 16px rgba(15, 23, 42, 0.12);
        border: 1px solid rgba(255, 255, 255, 0.08);
    }
    .hero-header h1 {
        margin: 0;
        font-size: 1.85rem;
        font-weight: 700;
        letter-spacing: -0.025em;
        color: #ffffff;
    }
    .hero-header p {
        margin: 0.4rem 0 0 0;
        color: #cbd5e1;
        font-size: 0.95rem;
        line-height: 1.4;
    }
    .hero-badge {
        display: inline-block;
        background: rgba(255, 255, 255, 0.15);
        color: #e2e8f0;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        padding: 3px 10px;
        border-radius: 20px;
        margin-bottom: 0.6rem;
        backdrop-filter: blur(4px);
    }

    /* Metric Cards */
    .fin-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
    }
    .metric-ribbon {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 1rem;
        margin: 1rem 0;
    }
    .metric-box {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1rem 1.25rem;
        border-left: 4px solid var(--brand-primary);
    }
    .metric-label {
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        color: #64748b;
        margin-bottom: 0.25rem;
    }
    .metric-value {
        font-size: 1.45rem;
        font-weight: 700;
        color: #0f172a;
        font-variant-numeric: tabular-nums;
    }
    .metric-sub {
        font-size: 0.8rem;
        color: #94a3b8;
        margin-top: 0.2rem;
    }

    /* Agent Stage Tracker Cards */
    .agent-tracker-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 0.85rem;
        margin: 1.25rem 0;
    }
    .agent-step {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 0.9rem 1.1rem;
        position: relative;
    }
    .agent-step.active {
        border-color: #3b82f6;
        background: #eff6ff;
        box-shadow: 0 0 0 1px #3b82f6;
    }
    .agent-step.completed {
        border-color: #a7f3d0;
        background: #f0fdf4;
    }
    .agent-step.waiting {
        border-color: #fde68a;
        background: #fffbeb;
    }
    .agent-step-title {
        font-size: 0.88rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }
    .agent-step-desc {
        font-size: 0.78rem;
        color: #64748b;
        line-height: 1.35;
    }

    /* Status Badges */
    .badge-clear {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        background: #ecfdf5;
        color: #059669;
        font-weight: 600;
        font-size: 0.8rem;
        padding: 3px 10px;
        border-radius: 6px;
        border: 1px solid #a7f3d0;
    }
    .badge-exception {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        background: #fffbeb;
        color: #d97706;
        font-weight: 600;
        font-size: 0.8rem;
        padding: 3px 10px;
        border-radius: 6px;
        border: 1px solid #fde68a;
    }
    .badge-review {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        background: #fef2f2;
        color: #dc2626;
        font-weight: 600;
        font-size: 0.8rem;
        padding: 3px 10px;
        border-radius: 6px;
        border: 1px solid #fecaca;
    }
    .badge-neutral {
        display: inline-flex;
        align-items: center;
        gap: 0.35rem;
        background: #f8fafc;
        color: #475569;
        font-weight: 600;
        font-size: 0.8rem;
        padding: 3px 10px;
        border-radius: 6px;
        border: 1px solid #e2e8f0;
    }

    /* Workflow Feed Items */
    .feed-item {
        padding: 0.45rem 0.65rem;
        border-radius: 6px;
        margin-bottom: 0.35rem;
        font-size: 0.88rem;
        display: flex;
        align-items: flex-start;
        gap: 0.5rem;
        line-height: 1.4;
    }
    .feed-success { background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; }
    .feed-warning { background: #fffbeb; color: #92400e; border: 1px solid #fef3c7; }
    .feed-error   { background: #fef2f2; color: #991b1b; border: 1px solid #fee2e2; }
    .feed-info    { background: #f8fafc; color: #1e293b; border: 1px solid #e2e8f0; }

    /* HITL Audit Banner */
    .hitl-banner {
        background: #fffbeb;
        border: 1px solid #f59e0b;
        border-left: 5px solid #d97706;
        border-radius: 10px;
        padding: 1.25rem 1.5rem;
        margin: 1.25rem 0;
    }
    .hitl-banner h4 {
        margin: 0 0 0.4rem 0;
        color: #b45309;
        font-size: 1.1rem;
        font-weight: 700;
    }
    .hitl-banner p {
        margin: 0;
        color: #78350f;
        font-size: 0.9rem;
    }

    /* Email Box */
    .email-container {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-left: 4px solid #1a237e;
        border-radius: 10px;
        padding: 1.25rem 1.5rem;
        margin-top: 1rem;
    }

    /* Dataset Banner */
    .dataset-banner {
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-left: 5px solid #1a237e;
        border-radius: 10px;
        padding: 1.1rem 1.4rem;
        margin-bottom: 1.25rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
    }
    .dataset-banner-title {
        font-size: 1.05rem;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 0.35rem;
    }
    .dataset-banner-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 1.2rem;
        font-size: 0.83rem;
        color: #64748b;
        font-variant-numeric: tabular-nums;
    }
</style>
""", unsafe_allow_html=True)


# --- Session State Management ---
def init_session_state():
    """Initialize all persistent and runtime state keys."""
    active_ds = ensure_active_dataset()
    defaults = {
        "thread_id": str(uuid.uuid4()),
        "phase": "idle",  # idle | running | waiting_missing | complete | error
        "active_dataset_id": active_ds.get("dataset_id"),
        "active_dataset_name": active_ds.get("name"),
        "active_dataset_version": active_ds.get("version", 1),
        "workflow_status": [],
        "agent_state": {},
        "graph": None,
        "interrupt_data": None,
        "pdf_path": None,
        "totals": None,
        "error": None,
        "recipient_email": "",
        "email_subject": "",
        "email_body": "",
        "email_source": "",
        "email_status": None,
        "prompt_input": "",
        "custom_expenses_list": None,
        "ingest_notice": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# --- Agent Orchestration Wrappers ---
def run_agent(
    request: str,
    model: str,
    custom_expenses: list = None,
    emp_name: str = "",
    dataset_id: str = None,
    dataset_version: int = None,
):
    """Execute the multi-agent graph with given parameters."""
    os.environ["OLLAMA_MODEL"] = model
    from agent import get_compiled_graph

    graph, _ = get_compiled_graph()
    config = {"configurable": {"thread_id": st.session_state["thread_id"]}}

    initial_state = {
        "messages": [],
        "user_request": request,
        "start_date": "",
        "end_date": "",
        "expense_type": "",
        "expenses": custom_expenses or [],
        "filtered_expenses": [],
        "categorized_expenses": [],
        "missing_data": [],
        "totals": {},
        "pdf_path": "",
        "workflow_status": [],
        "awaiting_input": "",
        "human_response": "",
        "error": "",
        "employee_name": emp_name or os.getenv("EMPLOYEE_NAME", ""),
        "target_employee": "",
        "recipient_email": "",
        "email_subject": "",
        "email_body": "",
        "email_status": "",
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
    }

    try:
        result = None
        for event in graph.stream(initial_state, config, stream_mode="values"):
            result = event

        current_state = graph.get_state(config)
        if current_state.tasks:
            return None, graph, current_state

        return result, graph, None

    except GraphInterrupt:
        state = graph.get_state(config)
        return None, graph, state


def resume_agent(graph, response_value):
    """Resume execution after a Human-in-the-Loop audit checkpoint."""
    config = {"configurable": {"thread_id": st.session_state["thread_id"]}}
    try:
        result = None
        for event in graph.stream(Command(resume=response_value), config, stream_mode="values"):
            result = event

        current_state = graph.get_state(config)
        if current_state.tasks:
            return None, current_state

        return result, None
    except GraphInterrupt:
        state = graph.get_state(config)
        return None, state


# --- Sidebar: System Diagnostics & Settings ---
with st.sidebar:
    st.markdown("### ⚙️ System Engine & Setup")
    st.caption("Multi-Agent LangGraph + Persistent SQLite Memory")

    ollama_model = st.text_input(
        "🤖 Local LLM (NLU Intent Parser)",
        value=os.getenv("OLLAMA_MODEL", "qwen3:4b"),
        help="Ollama model for intent parsing and email drafting. Regex fallback is active if offline.",
    )

    st.divider()

    # Session Diagnostics
    st.markdown("#### 🔒 Active Execution Session")
    st.code(st.session_state["thread_id"][:18] + "...", language="text")

    status_color = {
        "idle": "⚪ Idle",
        "running": "🔵 Running Multi-Agent Workflow",
        "waiting_missing": "🟡 Human Review Required",
        "complete": "🟢 Completed",
        "error": "🔴 Error Encountered",
    }.get(st.session_state["phase"], "⚪ Idle")
    st.caption(f"**State:** {status_color}")

    # Database Status
    db_path = DEFAULT_MEMORY_DB_PATH
    db_exists = os.path.exists(db_path)
    db_badge = "🟢 Connected" if db_exists else "🟡 Not Initialized"
    st.caption(f"**SQLite Memory:** {db_badge} (`data/expense_memory.db`)")

    st.divider()

    # Reset Action
    if st.button("🔄 Reset Agent Session", use_container_width=True):
        st.session_state["thread_id"] = str(uuid.uuid4())
        st.session_state["phase"] = "idle"
        st.session_state["workflow_status"] = []
        st.session_state["agent_state"] = {}
        st.session_state["graph"] = None
        st.session_state["interrupt_data"] = None
        st.session_state["pdf_path"] = None
        st.session_state["totals"] = None
        st.session_state["error"] = None
        st.session_state["recipient_email"] = ""
        st.session_state["email_subject"] = ""
        st.session_state["email_body"] = ""
        st.session_state["email_source"] = ""
        st.session_state["email_status"] = None
        st.session_state["prompt_input"] = ""
        st.session_state["custom_expenses_list"] = None
        st.rerun()

    st.caption("Engine: LangGraph 0.4+ | ReportLab 4.2+ | SQLite Checkpointer")


# --- Hero Application Header ---
st.markdown("""
<div class="hero-header">
    <div class="hero-badge">Enterprise Multi-Agent FinTech Platform</div>
    <h1>AI Expense Report Management System</h1>
    <p>Autonomous Natural-Language Processing &bull; Multi-Agent Compliance Audit &bull; Cryptographic Persistent Memory &bull; Publication-Grade PDF Reports</p>
</div>
""", unsafe_allow_html=True)


# --- Top-Level Navigation Tabs ---
nav_tab1, nav_tab2, nav_tab3, nav_tab4 = st.tabs([
    "📊 Executive Workspace & Execution",
    "📜 Prompt & Report Run History",
    "🧠 Persistent SQLite Memory & Ingestion",
    "🛡️ Compliance & Validation Issues",
])


# ===========================================================================
# TAB 1: EXECUTIVE WORKSPACE & EXECUTION
# ===========================================================================
with nav_tab1:
    # 0. Active Dataset Header Banner & Management
    active_ds = ensure_active_dataset()
    st.session_state["active_dataset_id"] = active_ds["dataset_id"]
    st.session_state["active_dataset_name"] = active_ds["name"]
    st.session_state["active_dataset_version"] = active_ds.get("version", 1)

    st.markdown(f"""
    <div class="dataset-banner">
        <div>
            <div class="dataset-banner-title">
                <span>📁 Active Dataset:</span> {active_ds['name']}
            </div>
            <div class="dataset-banner-meta">
                <span>🏷️ ID: <strong>{active_ds['dataset_id']}</strong></span>
                <span>🔢 Version: <strong>v{active_ds.get('version', 1)}</strong></span>
                <span>📊 Transactions: <strong>{active_ds.get('row_count', 0):,}</strong></span>
                <span>🔒 SHA-256: <code>{active_ds.get('file_hash', '')[:10]}...</code></span>
            </div>
        </div>
        <div>
            <span class="badge-clear">🟢 ACTIVE DATASET</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Dataset Switching & Ingestion Drawer
    with st.expander("📥 Active Expense Data Input (Table Editor & CSV Upload)", expanded=False):
        col_ds1, col_ds2 = st.columns(2)
        with col_ds1:
            st.markdown("##### 📂 Select Saved Dataset")
            saved_datasets = list_datasets()
            ds_options = {
                f"{d['name']} (v{d.get('version', 1)}, {d.get('row_count', 0)} rows) [{d['dataset_id'][:10]}]": d['dataset_id']
                for d in saved_datasets
            }
            curr_labels = [lbl for lbl, did in ds_options.items() if did == active_ds["dataset_id"]]
            default_idx = list(ds_options.keys()).index(curr_labels[0]) if curr_labels else 0
            selected_label = st.selectbox(
                "Saved Datasets in SQLite Memory:",
                list(ds_options.keys()),
                index=default_idx,
                key="select_saved_dataset_dropdown",
            )
            if st.button("Activate Selected Dataset", use_container_width=True):
                target_id = ds_options[selected_label]
                if target_id != active_ds["dataset_id"]:
                    set_active_dataset(target_id)
                    st.session_state["active_dataset_id"] = target_id
                    st.session_state["custom_expenses_list"] = None
                    st.rerun()

        with col_ds2:
            st.markdown("##### 📤 Upload New Scenario CSV")
            uploaded_file = st.file_uploader(
                "Upload custom CSV file:",
                type=["csv"],
                key="workspace_upload_csv_input",
            )
            if uploaded_file is not None:
                file_bytes = uploaded_file.getvalue()
                f_hash = hashlib.sha256(file_bytes).hexdigest()
                if f_hash != active_ds.get("file_hash"):
                    try:
                        df_up = pd.read_csv(uploaded_file)
                        up_records = _clean_editor_records(df_up.to_dict(orient="records"))
                        new_ds = create_or_get_dataset(
                            name=uploaded_file.name,
                            file_hash=f_hash,
                            row_count=len(up_records),
                            schema={"columns": list(df_up.columns)},
                        )
                        set_active_dataset(new_ds["dataset_id"])
                        save_expenses(
                            expenses=up_records,
                            dataset_id=new_ds["dataset_id"],
                            dataset_version=1,
                            source_name=uploaded_file.name,
                        )
                        st.session_state["active_dataset_id"] = new_ds["dataset_id"]
                        st.session_state["active_dataset_name"] = new_ds["name"]
                        st.session_state["active_dataset_version"] = 1
                        st.session_state["custom_expenses_list"] = up_records
                        st.success(f"✓ Ingested and activated '{uploaded_file.name}' with {len(up_records)} transactions.")
                        st.rerun()
                    except Exception as ex:
                        st.error(f"Failed to ingest uploaded CSV: {ex}")

    # 1. Interactive Table Editor (Primary Workspace)
    st.markdown("#### 📝 Interactive Expense Data Editor (Source of Truth)")
    st.caption("Review, edit, add, or delete transactions for the active dataset. Cell modifications and newly added rows are validated in real time:")

    if st.session_state.get("custom_expenses_list") is None:
        db_recs = retrieve_expenses_from_db(
            dataset_id=active_ds["dataset_id"],
            dataset_version=active_ds.get("version", 1),
            include_excluded=False,
        )
        if not db_recs:
            try:
                csv_path = os.getenv("EXPENSE_CSV_PATH", "data/expenses.csv")
                db_recs = get_expenses(csv_path)
            except Exception:
                db_recs = []
        st.session_state["custom_expenses_list"] = db_recs

    current_records = st.session_state.get("custom_expenses_list") or []

    if current_records:
        df_editor_input = pd.DataFrame(current_records)
        display_cols = [
            c for c in ["record_id", "date", "employee", "description", "merchant", "category", "amount", "receipt_status", "location"]
            if c in df_editor_input.columns
        ]
        if not display_cols:
            display_cols = list(df_editor_input.columns)
        df_editor_display = df_editor_input[display_cols]
    else:
        df_editor_display = pd.DataFrame(columns=[
            "record_id", "date", "employee", "description", "merchant", "category", "amount", "receipt_status", "location"
        ])

    edited_df = st.data_editor(
        df_editor_display,
        num_rows="dynamic",
        use_container_width=True,
        key="main_workspace_table_editor",
        disabled=(st.session_state["phase"] not in ("idle", "complete", "error")),
    )

    col_save_v, col_reload, col_blank = st.columns([1.6, 1.3, 2.1])
    with col_save_v:
        curr_ver = active_ds.get("version", 1)
        if st.button(f"💾 Save Table as Version v{curr_ver + 1}", use_container_width=True):
            clean_edited = _clean_editor_records(edited_df.to_dict(orient="records"))
            new_v = increment_dataset_version(
                dataset_id=active_ds["dataset_id"],
                updated_records=clean_edited,
            )
            st.session_state["custom_expenses_list"] = clean_edited
            st.session_state["active_dataset_version"] = new_v
            st.success(f"✓ Saved {len(clean_edited)} records under Version v{new_v} in SQLite persistent memory.")
            st.rerun()

    with col_reload:
        if st.button("🔄 Discard Unsaved Edits", use_container_width=True):
            st.session_state["custom_expenses_list"] = None
            st.rerun()

    if not edited_df.empty:
        st.session_state["custom_expenses_list"] = _clean_editor_records(edited_df.to_dict(orient="records"))

    st.divider()

    # 2. Request Formulation
    st.markdown("#### 💬 Request Formulation")
    st.caption("Enter your expense request in natural language:")

    user_req = st.text_area(
        "Request Description",
        value=st.session_state.get("prompt_input", ""),
        height=75,
        placeholder="e.g. Generate all expenses report for Ravi Kumar or Travel expenses for August 2026",
        disabled=(st.session_state["phase"] not in ("idle", "complete", "error")),
        label_visibility="collapsed",
    )
    if user_req != st.session_state.get("prompt_input"):
        st.session_state["prompt_input"] = user_req

    # 3. Action Control: Execute Multi-Agent Workflow
    col_exec, col_phase_badge = st.columns([3, 1])
    with col_exec:
        execute_clicked = st.button(
            "🚀 Execute Multi-Agent Workflow",
            type="primary",
            use_container_width=True,
            disabled=(st.session_state["phase"] not in ("idle", "complete", "error")),
        )

    with col_phase_badge:
        phase_badges = {
            "idle": '<div class="badge-neutral" style="width:100%; justify-content:center; padding:10px 0;">⚪ Ready to Execute</div>',
            "running": '<div class="badge-neutral" style="width:100%; justify-content:center; padding:10px 0; background:#eff6ff; color:#2563eb; border-color:#bfdbfe;">⚡ Processing Workflow...</div>',
            "waiting_missing": '<div class="badge-review" style="width:100%; justify-content:center; padding:10px 0;">⚠️ Human Review Required</div>',
            "complete": '<div class="badge-clear" style="width:100%; justify-content:center; padding:10px 0;">✅ Execution Completed</div>',
            "error": '<div class="badge-review" style="width:100%; justify-content:center; padding:10px 0;">❌ Execution Error</div>',
        }
        st.markdown(phase_badges.get(st.session_state["phase"], ""), unsafe_allow_html=True)

    # Trigger Agent Execution
    if execute_clicked:
        if not user_req.strip():
            st.warning("⚠️ Please enter an expense report request in the prompt box before executing.")
        else:
            st.session_state["phase"] = "running"
            st.session_state["workflow_status"] = []
            st.session_state["error"] = None
            st.session_state["thread_id"] = str(uuid.uuid4())

        with st.spinner("🤖 Multi-agent workflow in progress..."):
            try:
                result, graph, interrupted_state = run_agent(
                    request=user_req,
                    model=ollama_model,
                    custom_expenses=st.session_state.get("custom_expenses_list"),
                    dataset_id=active_ds["dataset_id"],
                    dataset_version=active_ds.get("version", 1),
                )

                st.session_state["graph"] = graph

                if result is not None:
                    st.session_state["workflow_status"] = result.get("workflow_status", [])
                    st.session_state["agent_state"] = result
                    st.session_state["pdf_path"] = result.get("pdf_path")
                    st.session_state["totals"] = result.get("totals")
                    st.session_state["phase"] = "complete"
                elif interrupted_state is not None:
                    state_values = interrupted_state.values
                    tasks = interrupted_state.tasks

                    st.session_state["workflow_status"] = state_values.get("workflow_status", [])
                    st.session_state["agent_state"] = state_values

                    if tasks:
                        interrupt_info = tasks[0].interrupts[0].value if tasks[0].interrupts else {}
                        st.session_state["interrupt_data"] = interrupt_info
                        st.session_state["phase"] = "waiting_missing"
                    st.rerun()

            except Exception as e:
                st.session_state["phase"] = "error"
                st.session_state["error"] = str(e)
                st.error(f"Multi-agent execution encountered an error: {str(e)}")

        st.rerun()

    # 4. Live Multi-Agent Orchestration Tracker
    st.markdown("#### 🤖 Multi-Agent Collaboration Stages")
    
    # Determine stage states
    agent_st = st.session_state.get("agent_state", {})
    status_list = st.session_state.get("workflow_status", [])
    
    # Stage 1: Expense Analysis
    s1_class = "agent-step"
    if st.session_state["phase"] == "running" and not agent_st.get("expense_analysis"):
        s1_class += " active"
    elif agent_st.get("expense_analysis"):
        s1_class += " completed"

    # Stage 2: Validation
    s2_class = "agent-step"
    if st.session_state["phase"] == "waiting_missing":
        s2_class += " waiting"
    elif agent_st.get("validation_findings") is not None and st.session_state["phase"] in ("complete", "waiting_missing"):
        s2_class += " completed"
    elif st.session_state["phase"] == "running" and agent_st.get("expense_analysis"):
        s2_class += " active"

    # Stage 3: Report Generation
    s3_class = "agent-step"
    if st.session_state["phase"] == "complete":
        s3_class += " completed"
    elif st.session_state["phase"] == "running" and agent_st.get("validation_findings") is not None:
        s3_class += " active"

    st.markdown(f"""
    <div class="agent-tracker-grid">
        <div class="{s1_class}">
            <div class="agent-step-title">
                <span>🤖</span> Agent 1: Expense Analysis
            </div>
            <div class="agent-step-desc">
                Natural-language intent parsing, dynamic employee matching & deterministic filtering.
            </div>
        </div>
        <div class="{s2_class}">
            <div class="agent-step-title">
                <span>🛡️</span> Agent 2: Validation Agent
            </div>
            <div class="agent-step-desc">
                Compliance auditing, missing receipt checks, non-zero validation & issue tracking.
            </div>
        </div>
        <div class="{s3_class}">
            <div class="agent-step-title">
                <span>📑</span> Agent 3: Report Generation
            </div>
            <div class="agent-step-desc">
                Integrity guard enforcement, deterministic math, PDF badge rendering & memory archival.
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 5. Chronological Workflow Activity Log
    if status_list:
        with st.expander("📋 Chronological Activity & Audit Log", expanded=(st.session_state["phase"] == "running")):
            for s in status_list:
                if s.startswith("✓") or "succeeded" in s:
                    st.markdown(f'<div class="feed-item feed-success"><span>✓</span><span>{s}</span></div>', unsafe_allow_html=True)
                elif s.startswith("⚠") or "Flagged" in s:
                    st.markdown(f'<div class="feed-item feed-warning"><span>⚠</span><span>{s}</span></div>', unsafe_allow_html=True)
                elif s.startswith("✗") or "failed" in s or "Aborted" in s:
                    st.markdown(f'<div class="feed-item feed-error"><span>✗</span><span>{s}</span></div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="feed-item feed-info"><span>ℹ</span><span>{s}</span></div>', unsafe_allow_html=True)

    # 6. Human-in-the-Loop Review Console
    if st.session_state["phase"] == "waiting_missing":
        interrupt_info = st.session_state.get("interrupt_data", {})
        issues = interrupt_info.get("issues", [])

        st.markdown("""
        <div class="hitl-banner">
            <h4>⚠️ Compliance Review: Incomplete or Flagged Transactions Detected</h4>
            <p>The Validation Agent detected records with null, zero, or missing values (e.g. missing amount, date, or receipt).
            You can <strong>input the missing values</strong>, <strong>exclude the incomplete records from counting</strong>, or <strong>authorize documented exceptions</strong>.</p>
        </div>
        """, unsafe_allow_html=True)

        # Render Table of Issues
        if issues:
            issues_table = []
            for item in issues:
                exp = item.get("expense", {})
                raw_amt = exp.get("amount", 0)
                try:
                    amt_num = float(raw_amt) if raw_amt is not None and not math.isnan(float(raw_amt)) else 0.0
                    amt_disp = f"₹{amt_num:,.2f}" if amt_num > 0 else "NULL / Missing (₹0.00)"
                except:
                    amt_disp = "NULL / Missing"

                date_val = exp.get("date") or "Missing Date"
                if str(date_val).lower() in ("nan", "none", "nat", ""):
                    date_val = "Missing Date"

                issues_table.append({
                    "Record ID": item.get("record_id", "N/A"),
                    "Employee": exp.get("employee", "N/A") or "Unknown",
                    "Date": date_val,
                    "Description": exp.get("description", "N/A") or "Missing",
                    "Merchant": exp.get("merchant", "N/A") or "Unknown",
                    "Amount": amt_disp,
                    "Detected Issue": item.get("message", "Validation Discrepancy"),
                    "Severity": item.get("severity", "medium").upper(),
                })
            st.dataframe(pd.DataFrame(issues_table), use_container_width=True)

        st.markdown("#### ⚡ Quick Actions")
        col_act1, col_act2 = st.columns(2)

        with col_act1:
            if st.button("❌ Exclude Flagged Items from Counting & Report", type="primary", use_container_width=True):
                graph = st.session_state["graph"]
                with st.spinner("Excluding incomplete items from calculations..."):
                    try:
                        res, new_interrupted = resume_agent(graph, "exclude")
                        if res is not None:
                            st.session_state["workflow_status"] = res.get("workflow_status", [])
                            st.session_state["agent_state"] = res
                            st.session_state["pdf_path"] = res.get("pdf_path")
                            st.session_state["totals"] = res.get("totals")
                            st.session_state["phase"] = "complete"
                        elif new_interrupted is not None:
                            vals = new_interrupted.values
                            st.session_state["workflow_status"] = vals.get("workflow_status", [])
                            st.session_state["agent_state"] = vals
                            st.session_state["phase"] = "waiting_missing"
                        st.rerun()
                    except Exception as ex:
                        st.session_state["error"] = str(ex)
                        st.session_state["phase"] = "error"
                        st.rerun()
            st.caption("Removes all incomplete or flagged transactions completely from the report and grand total calculations.")

        with col_act2:
            if st.button("✅ Authorize Documented Exceptions (Include As-Is)", use_container_width=True):
                graph = st.session_state["graph"]
                with st.spinner("Authorizing managerial exceptions and generating verified report..."):
                    try:
                        res, new_interrupted = resume_agent(graph, "include")
                        if res is not None:
                            st.session_state["workflow_status"] = res.get("workflow_status", [])
                            st.session_state["agent_state"] = res
                            st.session_state["pdf_path"] = res.get("pdf_path")
                            st.session_state["totals"] = res.get("totals")
                            st.session_state["phase"] = "complete"
                        elif new_interrupted is not None:
                            vals = new_interrupted.values
                            st.session_state["workflow_status"] = vals.get("workflow_status", [])
                            st.session_state["agent_state"] = vals
                            st.session_state["phase"] = "waiting_missing"
                        st.rerun()
                    except Exception as ex:
                        st.session_state["error"] = str(ex)
                        st.session_state["phase"] = "error"
                        st.rerun()
            st.caption("Includes the flagged items under authorized managerial exception policy with official audit badge.")

        # Interactive Field Input & Correction Section
        st.markdown("#### ✏️ Input Missing Values for Flagged Records")
        with st.container():
            st.caption("Select any flagged record to provide its missing amount, date, or documentation, then revalidate:")
            if issues:
                rec_choices = []
                rec_map = {}
                for m in issues:
                    rid = m.get("record_id")
                    if rid:
                        exp = m.get("expense", {})
                        desc = exp.get("description", "Item")
                        rec_choices.append(f"{rid} — {desc}")
                        rec_map[f"{rid} — {desc}"] = m

                if rec_choices:
                    chosen_label = st.selectbox("Select Incomplete Record to Input Value", rec_choices)
                    chosen_issue = rec_map[chosen_label]
                    chosen_rid = chosen_issue.get("record_id")
                    chosen_exp = chosen_issue.get("expense", {})

                    c_col1, c_col2, c_col3 = st.columns(3)
                    with c_col1:
                        curr_amt = float(chosen_exp.get("amount", 0) or 0)
                        input_amount = st.number_input(
                            "Input Amount (₹)",
                            min_value=0.01,
                            value=curr_amt if curr_amt > 0 else 1000.0,
                            step=100.0,
                            help="Provide a positive non-zero financial amount for this transaction.",
                        )
                    with c_col2:
                        curr_date = str(chosen_exp.get("date", "")).strip()
                        if curr_date.lower() in ("nan", "none", "nat", ""):
                            curr_date = datetime.now().strftime("%Y-%m-%d")
                        input_date = st.text_input(
                            "Input Expense Date (YYYY-MM-DD)",
                            value=curr_date,
                            help="Transaction date in YYYY-MM-DD format.",
                        )
                    with c_col3:
                        input_receipt = st.selectbox(
                            "Receipt Status",
                            ["Verified", "Missing", "Approved by Manager"],
                            index=0 if chosen_exp.get("receipt_status") == "Verified" else 2,
                        )

                    c_act1, c_act2, c_act3 = st.columns([1.5, 1.2, 1.3])
                    with c_act1:
                        if st.button("💾 Save Value & Revalidate Workflow", type="primary"):
                            graph = st.session_state["graph"]
                            correction_payload = {
                                "action": "correct",
                                "record_id": chosen_rid,
                                "updates": {
                                    "amount": input_amount,
                                    "date": input_date,
                                    "receipt_status": input_receipt,
                                }
                            }
                            with st.spinner("Applying values and revalidating..."):
                                try:
                                    res, new_interrupted = resume_agent(graph, correction_payload)
                                    if res is not None:
                                        st.session_state["workflow_status"] = res.get("workflow_status", [])
                                        st.session_state["agent_state"] = res
                                        st.session_state["pdf_path"] = res.get("pdf_path")
                                        st.session_state["totals"] = res.get("totals")
                                        st.session_state["phase"] = "complete"
                                    elif new_interrupted is not None:
                                        vals = new_interrupted.values
                                        st.session_state["workflow_status"] = vals.get("workflow_status", [])
                                        st.session_state["agent_state"] = vals
                                        st.session_state["phase"] = "waiting_missing"
                                    st.rerun()
                                except Exception as ex:
                                    st.session_state["error"] = str(ex)
                                    st.session_state["phase"] = "error"
                                    st.rerun()

                    with c_act2:
                        if st.button(f"🗑️ Exclude Only {chosen_rid}"):
                            graph = st.session_state["graph"]
                            with st.spinner(f"Excluding {chosen_rid} from calculations..."):
                                try:
                                    res, new_interrupted = resume_agent(graph, {"action": "exclude_single", "record_id": chosen_rid})
                                    if res is not None:
                                        st.session_state["workflow_status"] = res.get("workflow_status", [])
                                        st.session_state["agent_state"] = res
                                        st.session_state["pdf_path"] = res.get("pdf_path")
                                        st.session_state["totals"] = res.get("totals")
                                        st.session_state["phase"] = "complete"
                                    elif new_interrupted is not None:
                                        vals = new_interrupted.values
                                        st.session_state["workflow_status"] = vals.get("workflow_status", [])
                                        st.session_state["agent_state"] = vals
                                        st.session_state["phase"] = "waiting_missing"
                                    st.rerun()
                                except Exception as ex:
                                    st.session_state["error"] = str(ex)
                                    st.session_state["phase"] = "error"
                                    st.rerun()

                    with c_act3:
                        if st.button(f"✅ Authorize Exception for {chosen_rid}"):
                            graph = st.session_state["graph"]
                            with st.spinner(f"Authorizing exception for {chosen_rid}..."):
                                try:
                                    res, new_interrupted = resume_agent(graph, {
                                        "action": "accept_single",
                                        "record_id": chosen_rid,
                                        "reason": "Authorized managerial exception in HITL review",
                                    })
                                    if res is not None:
                                        st.session_state["workflow_status"] = res.get("workflow_status", [])
                                        st.session_state["agent_state"] = res
                                        st.session_state["pdf_path"] = res.get("pdf_path")
                                        st.session_state["totals"] = res.get("totals")
                                        st.session_state["phase"] = "complete"
                                    elif new_interrupted is not None:
                                        vals = new_interrupted.values
                                        st.session_state["workflow_status"] = vals.get("workflow_status", [])
                                        st.session_state["agent_state"] = vals
                                        st.session_state["phase"] = "waiting_missing"
                                    st.rerun()
                                except Exception as ex:
                                    st.session_state["error"] = str(ex)
                                    st.session_state["phase"] = "error"
                                    st.rerun()

    # 7. Executive Financial Metrics & Generated Report Results
    if st.session_state["phase"] in ("complete", "error"):
        st.divider()
        totals = st.session_state.get("totals")
        pdf_path = st.session_state.get("pdf_path")
        agent_st = st.session_state.get("agent_state", {})
        val_status = agent_st.get("validation_status", "Clear")

        if totals and totals.get("grand_total") is not None:
            st.markdown("#### 📊 Executive Financial Summary")

            # Validation Status Callout
            if "exception" in val_status.lower():
                st.markdown(
                    '<div class="badge-exception" style="font-size:0.95rem; padding:6px 14px; margin-bottom:1rem;">'
                    '🛡️ VALIDATION STATUS: REVIEWED WITH DOCUMENTED EXCEPTIONS'
                    '</div>',
                    unsafe_allow_html=True,
                )
            elif "clear" in val_status.lower():
                st.markdown(
                    '<div class="badge-clear" style="font-size:0.95rem; padding:6px 14px; margin-bottom:1rem;">'
                    '✅ VALIDATION STATUS: VERIFIED & CLEAR (ZERO OUTSTANDING ISSUES)'
                    '</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="badge-review" style="font-size:0.95rem; padding:6px 14px; margin-bottom:1rem;">'
                    f'⚠️ VALIDATION STATUS: {val_status.upper()}'
                    '</div>',
                    unsafe_allow_html=True,
                )

            # Metric Ribbon
            col_m1, col_m2, col_m3, col_m4 = st.columns(4)
            with col_m1:
                st.markdown(f"""
                <div class="metric-box">
                    <div class="metric-label">Grand Total</div>
                    <div class="metric-value">₹{totals.get('grand_total', 0):,.2f}</div>
                    <div class="metric-sub">{totals.get('transaction_count', 0)} Transactions Total</div>
                </div>
                """, unsafe_allow_html=True)

            with col_m2:
                missing_amt = totals.get("missing_receipt_total", 0)
                st.markdown(f"""
                <div class="metric-box" style="border-left-color: {'#dc2626' if missing_amt > 0 else '#059669'};">
                    <div class="metric-label">Missing Receipts Total</div>
                    <div class="metric-value">₹{missing_amt:,.2f}</div>
                    <div class="metric-sub">{'Flagged for review' if missing_amt > 0 else '100% Documentation'}</div>
                </div>
                """, unsafe_allow_html=True)

            with col_m3:
                emp_name = agent_st.get("employee_name", "Team")
                st.markdown(f"""
                <div class="metric-box" style="border-left-color: #2563eb;">
                    <div class="metric-label">Target Entity</div>
                    <div class="metric-value" style="font-size:1.15rem; text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">{emp_name}</div>
                    <div class="metric-sub">{agent_st.get('expense_type', 'Travel').title()} Expenses</div>
                </div>
                """, unsafe_allow_html=True)

            with col_m4:
                run_id = agent_st.get("report_run_id", "REP-ACTIVE")
                st.markdown(f"""
                <div class="metric-box" style="border-left-color: #64748b;">
                    <div class="metric-label">Audit Run ID</div>
                    <div class="metric-value" style="font-size:1.1rem;">{run_id[:14]}</div>
                    <div class="metric-sub">Archived in SQLite Memory</div>
                </div>
                """, unsafe_allow_html=True)

            # Category Breakdown Tabs/Pills
            cat_totals = totals.get("category_totals", {})
            if cat_totals:
                st.markdown("**Category Allocation:**")
                cat_cols = st.columns(min(len(cat_totals), 5))
                for idx, (cat, amt) in enumerate(sorted(cat_totals.items())):
                    with cat_cols[idx % len(cat_cols)]:
                        st.metric(label=cat, value=f"₹{amt:,.0f}")

        # PDF Download Section
        if pdf_path and os.path.exists(pdf_path):
            st.markdown("#### 📑 Publication-Grade PDF Report")
            pdf_size_kb = os.path.getsize(pdf_path) / 1024
            with open(pdf_path, "rb") as pf:
                pdf_bytes = pf.read()

            col_pdf_btn, col_pdf_meta = st.columns([1.5, 2.5])
            with col_pdf_btn:
                st.download_button(
                    label=f"⬇️ Download {os.path.basename(pdf_path)}",
                    data=pdf_bytes,
                    file_name=os.path.basename(pdf_path),
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )
            with col_pdf_meta:
                st.caption(f"**Generated File:** `{os.path.basename(pdf_path)}` ({pdf_size_kb:.1f} KB) &bull; Official ReportLab Vector Format")

            # AI Email Dispatch Console
            st.markdown("#### 📧 AI Executive Email Dispatch Console")
            st.caption("Drafted autonomously by **Qwen 3** (local Ollama) with deterministic financial summary attached:")

            # Prepare initial draft
            if not st.session_state.get("email_subject"):
                with st.spinner("🤖 Qwen 3 is composing executive email summary..."):
                    emp_name = agent_st.get("employee_name") or os.getenv("EMPLOYEE_NAME", "Employee")
                    draft = generate_email_draft(
                        totals=totals,
                        employee_name=emp_name,
                        start_date=agent_st.get("start_date", ""),
                        end_date=agent_st.get("end_date", ""),
                        expense_type=agent_st.get("expense_type", "travel"),
                        missing_data=agent_st.get("missing_data", []),
                        model_name=ollama_model,
                    )
                    st.session_state["email_subject"] = draft.get("subject", "")
                    st.session_state["email_body"] = draft.get("body", "")
                    st.session_state["email_source"] = draft.get("source", "qwen3")

            badge_text = "🤖 Drafted by Qwen 3 (Ollama)" if st.session_state.get("email_source") == "qwen3" else "📋 Structured Deterministic Template"
            st.markdown(f'<div class="badge-neutral" style="margin-bottom:0.75rem;">{badge_text}</div>', unsafe_allow_html=True)

            col_em1, col_em2 = st.columns([2.5, 1.5])
            with col_em1:
                recip_email = st.text_input(
                    "Recipient Email Address",
                    value=st.session_state.get("recipient_email", ""),
                    placeholder="e.g. finance-director@company.com",
                    key="field_recipient_email",
                )
                st.session_state["recipient_email"] = recip_email

            with col_em2:
                st.write("")
                st.write("")
                if st.button("✨ Re-draft with Qwen 3", use_container_width=True):
                    with st.spinner("🤖 Qwen 3 is regenerating draft..."):
                        draft = generate_email_draft(
                            totals=totals,
                            employee_name=agent_st.get("employee_name", "Employee"),
                            start_date=agent_st.get("start_date", ""),
                            end_date=agent_st.get("end_date", ""),
                            expense_type=agent_st.get("expense_type", "travel"),
                            missing_data=agent_st.get("missing_data", []),
                            model_name=ollama_model,
                        )
                        st.session_state["email_subject"] = draft.get("subject", "")
                        st.session_state["email_body"] = draft.get("body", "")
                        st.session_state["email_source"] = draft.get("source", "qwen3")
                        st.rerun()

            st.text_input("Email Subject Line", value=st.session_state.get("email_subject", ""), key="field_email_subject")
            st.text_area("Email Executive Body", value=st.session_state.get("email_body", ""), height=150, key="field_email_body")

            if st.button("📤 Send Expense Report via Email", type="primary", use_container_width=False):
                to_addr = st.session_state.get("recipient_email", "").strip()
                if not to_addr:
                    st.warning("⚠️ Please provide a valid recipient email address.")
                else:
                    with st.spinner("🚀 Dispatching email with attached PDF report..."):
                        dispatch_res = send_email_report(
                            to_email=to_addr,
                            subject=st.session_state.get("field_email_subject", st.session_state.get("email_subject", "")),
                            body=st.session_state.get("field_email_body", st.session_state.get("email_body", "")),
                            pdf_path=pdf_path,
                            resend_api_key=os.getenv("RESEND_API_KEY", ""),
                            resend_from=os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev"),
                        )
                        st.session_state["email_status"] = dispatch_res

            # Status Message
            em_status = st.session_state.get("email_status")
            if em_status:
                if em_status.get("success"):
                    if em_status.get("simulated"):
                        st.info(f"ℹ️ {em_status['message']}")
                    else:
                        st.success(f"{em_status['message']}")
                else:
                    st.error(f"❌ {em_status['message']}")

        # Errors if any
        if st.session_state.get("error"):
            st.error(f"⚠️ Error Notice: {st.session_state['error']}")

        # Debug State Expander
        with st.expander("🔍 Agent Graph State Inspector (Audit & Debug)", expanded=False):
            st.json({
                k: v for k, v in agent_st.items()
                if k in ("report_run_id", "user_request", "start_date", "end_date", "expense_type", "employee_name", "validation_status", "pdf_path")
            })
            cat_list = agent_st.get("categorized_expenses") or agent_st.get("filtered_expenses", [])
            if cat_list:
                st.markdown("**Audited Line Items:**")
                st.dataframe(pd.DataFrame(cat_list), use_container_width=True)


# ===========================================================================
# TAB 2: PROMPT & REPORT RUN HISTORY
# ===========================================================================
with nav_tab2:
    st.markdown("### 📜 Previous Prompts & Stored Report Runs")
    st.caption("Searchable historical audit trail of generated reports stored in SQLite persistent memory (`report_runs` table).")

    active_ds_id = st.session_state.get("active_dataset_id")
    active_name = st.session_state.get("active_dataset_name", "Current")
    col_sc1, col_sc2 = st.columns([2, 2])
    with col_sc1:
        scope_history = st.checkbox(
            f"Filter strictly to active dataset ({active_name})",
            value=True,
            key="filter_history_active_toggle",
        )

    try:
        target_ds = active_ds_id if scope_history else None
        history_runs = get_report_history(dataset_id=target_ds, limit=50)
    except Exception as e:
        history_runs = []
        st.warning(f"Could not load report history: {e}")

    if not history_runs:
        st.info("ℹ️ No historical report runs recorded for this dataset yet. Generate your first report in the Executive Workspace tab to see records archived here.")
    else:
        # History Statistics Ribbon
        h_total = len(history_runs)
        h_clear = sum(1 for r in history_runs if "clear" in str(r.get("validation_status", "")).lower())
        h_except = sum(1 for r in history_runs if "exception" in str(r.get("validation_status", "")).lower())

        col_h1, col_h2, col_h3 = st.columns(3)
        with col_h1:
            st.metric("Total Stored Runs", h_total)
        with col_h2:
            st.metric("Verified & Clear", h_clear)
        with col_h3:
            st.metric("Reviewed with Exceptions", h_except)

        st.divider()

        # Search & Filter Controls
        col_s1, col_s2 = st.columns([2.5, 1.5])
        with col_s1:
            search_query = st.text_input("🔍 Search History by Prompt or Employee", placeholder="e.g. Priya Sharma, August, Travel")
        with col_s2:
            status_filter = st.selectbox("Filter by Status", ["All Statuses", "Clear", "Reviewed with Exceptions", "Needs Human Review"])

        # Filter runs
        filtered_runs = history_runs
        if search_query.strip():
            sq = search_query.strip().lower()
            filtered_runs = [r for r in filtered_runs if sq in str(r.get("user_request", "")).lower() or sq in str(r.get("report_id", "")).lower()]

        if status_filter != "All Statuses":
            filtered_runs = [r for r in filtered_runs if status_filter.lower() in str(r.get("validation_status", "")).lower()]

        st.caption(f"Showing **{len(filtered_runs)}** matching report runs:")

        for run in filtered_runs:
            rep_id = run.get("report_id", "REP-UNKNOWN")
            req_text = run.get("user_request", "Expense Request")
            val_stat = run.get("validation_status", "Clear")
            grand_tot = run.get("grand_total", 0.0)
            txn_count = run.get("transaction_count", 0)
            created_ts = run.get("created_at", "")
            pdf_file = run.get("report_file_path", "")

            # Format status badge
            if "exception" in val_stat.lower():
                badge_html = '<span class="badge-exception">🛡️ REVIEWED WITH EXCEPTIONS</span>'
            elif "clear" in val_stat.lower():
                badge_html = '<span class="badge-clear">✅ VERIFIED & CLEAR</span>'
            else:
                badge_html = f'<span class="badge-review">⚠️ {val_stat.upper()}</span>'

            with st.container():
                st.markdown(f"""
                <div class="fin-card" style="margin-bottom: 0.75rem;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
                        <span style="font-weight:700; color:#1a237e; font-size:1.05rem;">{rep_id}</span>
                        {badge_html}
                    </div>
                    <div style="font-size:0.95rem; color:#0f172a; font-weight:500; margin-bottom:0.4rem;">
                        "{req_text}"
                    </div>
                    <div style="display:flex; gap:1.5rem; font-size:0.83rem; color:#64748b; font-variant-numeric:tabular-nums;">
                        <span>💰 Grand Total: <strong style="color:#0f172a;">₹{grand_tot:,.2f}</strong></span>
                        <span>📊 Transactions: <strong style="color:#0f172a;">{txn_count}</strong></span>
                        <span>🕒 Date: <strong style="color:#0f172a;">{created_ts[:19].replace('T', ' ')}</strong></span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1.2])
                with col_btn1:
                    if st.button(f"📋 Load Prompt", key=f"load_{rep_id}"):
                        st.session_state["prompt_input"] = req_text
                        st.success(f"Loaded prompt into workspace! Switch to the Executive Workspace tab to run.")
                with col_btn2:
                    if st.button(f"▶️ Run Again", key=f"rerun_{rep_id}"):
                        st.session_state["prompt_input"] = req_text
                        st.session_state["thread_id"] = str(uuid.uuid4())
                        st.session_state["phase"] = "running"
                        st.session_state["workflow_status"] = []
                        st.session_state["error"] = None
                        with st.spinner("Re-executing workflow..."):
                            res, gr, intr = run_agent(
                                req_text,
                                ollama_model,
                                dataset_id=run.get("dataset_id") or active_ds_id,
                                dataset_version=run.get("dataset_version", 1),
                            )
                            st.session_state["graph"] = gr
                            if res is not None:
                                st.session_state["workflow_status"] = res.get("workflow_status", [])
                                st.session_state["agent_state"] = res
                                st.session_state["pdf_path"] = res.get("pdf_path")
                                st.session_state["totals"] = res.get("totals")
                                st.session_state["phase"] = "complete"
                            elif intr is not None:
                                st.session_state["phase"] = "waiting_missing"
                                st.session_state["interrupt_data"] = intr.tasks[0].interrupts[0].value if intr.tasks else {}
                        st.rerun()
                with col_btn3:
                    if pdf_file and os.path.exists(pdf_file):
                        with open(pdf_file, "rb") as hf:
                            st.download_button(
                                label=f"⬇️ PDF ({os.path.basename(pdf_file)[:16]}...)",
                                data=hf.read(),
                                file_name=os.path.basename(pdf_file),
                                mime="application/pdf",
                                key=f"dl_{rep_id}",
                            )
                st.write("")


# ===========================================================================
# TAB 3: PERSISTENT SQLITE MEMORY & INGESTION
# ===========================================================================
with nav_tab3:
    st.markdown("### 🧠 Persistent SQLite Memory Architecture")
    st.caption("Demonstrating strict database separation, SHA-256 batch deduplication, and cross-session entity recall.")

    # Two-Tier Separation Explanation
    st.markdown("""
    <div style="background:#ffffff; border:1px solid #e2e8f0; border-radius:10px; padding:1.2rem; margin-bottom:1.25rem;">
        <div style="font-weight:700; color:#1a237e; font-size:1rem; margin-bottom:0.4rem;">
            🏛️ Architectural Separation of Storage
        </div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:1rem; font-size:0.85rem; color:#475569;">
            <div style="background:#f8fafc; padding:0.85rem; border-radius:8px; border-left:3px solid #1a237e;">
                <strong style="color:#0f172a;">1. Business Memory Database (data/expense_memory.db)</strong><br>
                Houses persistent domain entities: datasets registry, expenses v2, cryptographic import hashes, validation findings, report runs, and audit trails.
            </div>
            <div style="background:#f8fafc; padding:0.85rem; border-radius:8px; border-left:3px solid #2563eb;">
                <strong style="color:#0f172a;">2. Workflow Checkpoint Database (.checkpoints/agent_state.db)</strong><br>
                Managed by LangGraph's SqliteSaver exclusively to serialize thread execution states during Human-in-the-Loop review interruptions.
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    active_ds_id = st.session_state.get("active_dataset_id")
    # Memory Statistics Dashboard
    try:
        mem_stats = get_memory_stats(dataset_id=active_ds_id)
    except Exception:
        mem_stats = {"total_expenses": 0, "unique_employees": 0, "unresolved_issues": 0, "total_reports": 0}

    col_ms1, col_ms2, col_ms3, col_ms4 = st.columns(4)
    with col_ms1:
        st.markdown(f"""
        <div class="metric-box">
            <div class="metric-label">Stored Transactions</div>
            <div class="metric-value">{mem_stats.get('total_expenses', 0):,}</div>
            <div class="metric-sub">Active Dataset</div>
        </div>
        """, unsafe_allow_html=True)
    with col_ms2:
        st.markdown(f"""
        <div class="metric-box" style="border-left-color: #2563eb;">
            <div class="metric-label">Unique Employees</div>
            <div class="metric-value">{mem_stats.get('unique_employees', 0)}</div>
            <div class="metric-sub">Active Dataset</div>
        </div>
        """, unsafe_allow_html=True)
    with col_ms3:
        unres = mem_stats.get('unresolved_issues', 0)
        st.markdown(f"""
        <div class="metric-box" style="border-left-color: {'#dc2626' if unres > 0 else '#059669'};">
            <div class="metric-label">Open Compliance Issues</div>
            <div class="metric-value">{unres}</div>
            <div class="metric-sub">validation_issues table</div>
        </div>
        """, unsafe_allow_html=True)
    with col_ms4:
        st.markdown(f"""
        <div class="metric-box" style="border-left-color: #64748b;">
            <div class="metric-label">Archived Report Runs</div>
            <div class="metric-value">{mem_stats.get('total_reports', 0)}</div>
            <div class="metric-sub">Active Dataset</div>
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    # Datasets Master Registry
    st.markdown("#### 🗃️ Datasets Master Registry")
    st.caption("All datasets registered in SQLite persistent memory with cryptographic SHA-256 integrity hashes:")
    all_ds = list_datasets()
    if all_ds:
        ds_display = []
        for d in all_ds:
            ds_display.append({
                "Dataset ID": d["dataset_id"],
                "Dataset Name": d["name"],
                "Version": f"v{d.get('version', 1)}",
                "Transactions": f"{d.get('row_count', 0):,}",
                "SHA-256 Hash": f"{d.get('file_hash', '')[:16]}...",
                "Status": "🟢 ACTIVE" if d.get("is_active") == 1 else "⚪ Inactive",
                "Last Updated": str(d.get("updated_at", ""))[:19].replace("T", " "),
            })
        st.dataframe(pd.DataFrame(ds_display), use_container_width=True)

    st.divider()

    # SQLite Database Table Explorer
    st.markdown("#### 🔍 Persistent SQLite Table Explorer")
    TABLE_OPTIONS = {
        "expenses (all transactions)": ("expenses_v2", "ORDER BY id DESC"),
        "datasets": ("datasets", "ORDER BY created_at DESC"),
        "validation_issues": ("validation_issues_v2", "ORDER BY id DESC"),
        "report_runs": ("report_runs_v2", "ORDER BY id DESC"),
        "audit_events": ("audit_events", "ORDER BY id DESC"),
        "import_batches": ("import_batches", "ORDER BY id DESC"),
    }
    table_choice = st.radio("Select Table to Inspect:", list(TABLE_OPTIONS.keys()), horizontal=True)
    actual_table, order_clause = TABLE_OPTIONS[table_choice]

    try:
        conn = get_connection()
        query = f"SELECT * FROM {actual_table} {order_clause} LIMIT 50;"
        table_df = pd.read_sql_query(query, conn)
        conn.close()

        st.caption(f"Displaying top **{len(table_df)}** latest records from `{actual_table}`:")
        st.dataframe(table_df, use_container_width=True)
    except Exception as ex:
        st.warning(f"Unable to read table `{actual_table}`: {ex}")

    st.divider()

    # Collapsed Advanced Diagnostics / Deduplication Demonstration
    with st.expander("⚙️ Advanced Diagnostics: Master CSV Ingestion & Deduplication Safety", expanded=False):
        st.caption("Demonstrating Ingestion Safety: Ingesting the master CSV repeatedly will skip identical records rather than creating duplicates.")
        col_ing1, col_ing2 = st.columns([2, 3])
        with col_ing1:
            ingest_clicked = st.button("📥 Ingest Master CSV to Memory", type="primary", use_container_width=True)

        if ingest_clicked:
            try:
                csv_path = os.getenv("EXPENSE_CSV_PATH", "data/expenses.csv")
                loaded_data = get_expenses(csv_path)
                res = save_expenses(loaded_data, source_name=os.path.basename(csv_path))
                st.session_state["ingest_notice"] = (
                    f"✓ Ingestion complete: **{res['inserted']}** new records inserted, "
                    f"**{res['skipped_duplicates']}** duplicates skipped. Batch ID: `{res['batch_id'][:12]}`"
                )
                st.rerun()
            except Exception as ex:
                st.error(f"Ingestion failed: {ex}")

        if st.session_state.get("ingest_notice"):
            st.success(st.session_state["ingest_notice"])


# ===========================================================================
# TAB 4: COMPLIANCE & VALIDATION ISSUES
# ===========================================================================
with nav_tab4:
    st.markdown("### 🛡️ Compliance & Audit Issue Management")
    st.caption("Track, audit, and resolve compliance discrepancies logged in SQLite persistent memory by the Validation Agent.")

    active_ds_id = st.session_state.get("active_dataset_id")
    active_ds_name = st.session_state.get("active_dataset_name", "Current")
    scope_issues = st.checkbox(
        f"Filter strictly to active dataset ({active_ds_name})",
        value=True,
        key="compliance_filter_active_checkbox",
    )
    target_ds = active_ds_id if scope_issues else None

    try:
        open_issues = get_unresolved_issues(dataset_id=target_ds)
    except Exception:
        open_issues = []

    if not open_issues:
        st.markdown("""
        <div class="fin-card" style="text-align:center; padding:2rem;">
            <div style="font-size:2rem; margin-bottom:0.5rem;">🎉</div>
            <div style="font-size:1.1rem; font-weight:700; color:#059669;">Zero Unresolved Compliance Issues</div>
            <div style="font-size:0.88rem; color:#64748b; margin-top:0.3rem;">All audited transactions are fully compliant or resolved with documented managerial exceptions.</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"**Found {len(open_issues)} Open Compliance Discrepancy Items:**")
        issues_df = pd.DataFrame(open_issues)
        disp_cols = [
            c for c in [
                "issue_id", "expense_record_id", "employee", "expense_date",
                "merchant", "amount", "issue_type", "message", "severity", "status"
            ] if c in issues_df.columns
        ]
        st.dataframe(issues_df[disp_cols], use_container_width=True)

        st.markdown("#### ✍️ Auditor Direct Resolution")
        st.caption("Document an authorized managerial exception or correction directly into SQLite memory:")

        col_res1, col_res2, col_res3 = st.columns([2, 1.5, 1.5])
        with col_res1:
            sel_issue = st.selectbox(
                "Select Issue to Resolve",
                [f"{x['issue_id']} — {x.get('employee', '')}: {x.get('message', '')}" for x in open_issues],
            )
        with col_res2:
            decision_options = {
                "❌ Exclude from Counting & Reports": "exclude",
                "✅ Authorize Managerial Exception": "accept_exception",
            }
            sel_label = st.selectbox("Decision", list(decision_options.keys()))
            sel_decision = decision_options[sel_label]
        with col_res3:
            st.write("")
            st.write("")
            if st.button("Apply Auditor Resolution", type="primary"):
                try:
                    issue_id_target = sel_issue.split(" — ")[0].strip()
                    target_item = next((x for x in open_issues if x["issue_id"] == issue_id_target), None)
                    if target_item:
                        apply_reviewer_decision(
                            action=sel_decision,
                            record_id=target_item.get("expense_record_id"),
                            dataset_id=target_item.get("dataset_id"),
                            reason="Manually audited and approved in Compliance Audit tab",
                        )
                        resolve_validation_issue(
                            issue_id=issue_id_target,
                            decision=sel_decision,
                            notes="Manually audited and approved in Compliance Audit tab",
                        )
                    else:
                        resolve_validation_issue(
                            issue_id=issue_id_target,
                            decision=sel_decision,
                            notes="Manually audited and approved in Compliance Audit tab",
                        )
                    # Invalidate session cached expense list so Tab 1 loads fresh database records
                    st.session_state["custom_expenses_list"] = None
                    st.success(f"✓ Recorded decision for {issue_id_target}: '{sel_label}'. Persistent memory updated — this decision will be remembered and the workflow will proceed without stopping for review.")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Failed to apply auditor resolution: {str(ex)}")


# --- Application Footer ---
st.divider()
st.markdown("""
<div style="display:flex; justify-content:space-between; align-items:center; color:#94a3b8; font-size:0.8rem;">
    <span>AI Expense Report Management System &bull; Enterprise FinTech Architecture</span>
    <span>LangGraph &bull; SQLite Persistent Memory &bull; ReportLab Vector PDF &bull; Ollama Qwen 3</span>
</div>
""", unsafe_allow_html=True)
