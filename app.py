"""
Streamlit UI for the AI Expense Report Agent.

Provides a clean, professional interface for interacting with
the LangGraph-based expense report agent. Supports:
- Natural-language request input
- Real-time workflow progress tracking
- Human-in-the-loop interaction for missing data review
- Professional PDF generation and download
- Agent state inspection
"""

import os
import uuid
import pandas as pd
# pyrefly: ignore[missing-import]
import streamlit as st
# pyrefly: ignore[missing-import]
from dotenv import load_dotenv

from langgraph.types import Command
from langgraph.errors import GraphInterrupt

from tools.email_tools import generate_email_draft, send_email_report

# Load environment variables
load_dotenv(override=True)

# --- Page Config ---
st.set_page_config(
    page_title="AI Expense Report Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS ---
st.markdown("""
<style>
    /* Main container */
    .main .block-container {
        padding-top: 2rem;
        max-width: 1100px;
    }
    
    /* Header styling */
    .agent-header {
        background: linear-gradient(135deg, #1a237e 0%, #283593 50%, #3949ab 100%);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        color: white;
        box-shadow: 0 4px 20px rgba(26, 35, 126, 0.3);
    }
    .agent-header h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    .agent-header p {
        margin: 0.5rem 0 0 0;
        opacity: 0.85;
        font-size: 1rem;
    }
    
    /* Status messages */
    .status-success {
        color: #2e7d32;
        padding: 2px 0;
        font-size: 0.95rem;
    }
    .status-warning {
        color: #e65100;
        padding: 2px 0;
        font-size: 0.95rem;
    }
    .status-error {
        color: #c62828;
        padding: 2px 0;
        font-size: 0.95rem;
    }
    .status-info {
        color: #1565c0;
        padding: 2px 0;
        font-size: 0.95rem;
    }
    
    /* Totals card */
    .totals-card {
        background: linear-gradient(135deg, #e8eaf6 0%, #c5cae9 100%);
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1rem 0;
        border-left: 4px solid #1a237e;
    }
    
    /* HITL prompt */
    .hitl-box {
        background: #fff3e0;
        border: 2px solid #ff9800;
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1rem 0;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #fafafa 0%, #f5f5f5 100%);
    }
    
    /* Progress animation */
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }
    .processing {
        animation: pulse 1.5s ease-in-out infinite;
    }
    
    /* Email Box styling */
    .email-card {
        background: linear-gradient(135deg, #f8fafd 0%, #eef2f7 100%);
        border: 1px solid #c5cae9;
        border-radius: 12px;
        padding: 1.5rem;
        margin: 1.5rem 0;
        border-left: 5px solid #1a237e;
    }
    .badge-qwen {
        display: inline-block;
        background: #e8eaf6;
        color: #1a237e;
        font-weight: 600;
        font-size: 0.82rem;
        padding: 4px 10px;
        border-radius: 20px;
        border: 1px solid #9fa8da;
    }
    .badge-template {
        display: inline-block;
        background: #f5f5f5;
        color: #424242;
        font-weight: 600;
        font-size: 0.82rem;
        padding: 4px 10px;
        border-radius: 20px;
        border: 1px solid #e0e0e0;
    }
</style>
""", unsafe_allow_html=True)


# --- Session State Initialization ---
def init_session_state():
    """Initialize all session state variables."""
    defaults = {
        "thread_id": str(uuid.uuid4()),
        "phase": "idle",          # idle | running | waiting_missing | complete | error
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
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# --- Sidebar ---
with st.sidebar:
    st.markdown("### ⚙️ Configuration")
    st.divider()
    
    ollama_model = st.text_input(
        "🤖 Ollama Model",
        value=os.getenv("OLLAMA_MODEL", "qwen3:4b"),
        help="The Ollama model to use for NLU. Requires Ollama running locally.",
    )
    

    st.divider()
    
    # Reset button
    if st.button("🔄 Reset Agent", width="stretch"):
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
        st.rerun()
    
    st.divider()
    st.caption("Built with LangGraph + Ollama + Streamlit")
    st.caption(f"Model: {ollama_model}")


# --- Header ---
st.markdown("""
<div class="agent-header">
    <h1>📊 AI Expense Report Agent</h1>
    <p>Autonomous Agentic AI for Expense Report Generation & Validation</p>
</div>
""", unsafe_allow_html=True)


# --- Main Content ---

# Request input
user_request = st.text_area(
    "💬 Your Request",
    value="Generate travel expense report for the month",
    height=80,
    placeholder="e.g., Generate travel expense report for the month",
    disabled=(st.session_state["phase"] not in ("idle", "complete", "error")),
)
 
# --- Expense Data Input Section ---
st.markdown("### 📥 Expense Data Input (Give the Agent Your Expenses)")

tab1, tab2 = st.tabs(["📂 Interactive Table Editor", "📤 Upload Custom CSV File"])

custom_expenses_list = None

with tab1:
    st.caption("View, edit, add, or delete transactions below before generating your report:")
    try:
        df_default = pd.read_csv(os.getenv("EXPENSE_CSV_PATH", "data/expenses.csv"))
    except Exception:
        df_default = pd.DataFrame(columns=["date", "description", "merchant", "amount", "category", "receipt_status", "employee", "payment_method"])
    
    edited_df = st.data_editor(
        df_default,
        num_rows="dynamic",
        use_container_width=True,
        key="editor_tab1",
        disabled=(st.session_state["phase"] not in ("idle", "complete", "error")),
    )
    if not edited_df.empty:
        records = edited_df.to_dict(orient="records")
        for r in records:
            if "date" in r and r["date"] is not None:
                r["date"] = str(r["date"]).split("T")[0]
            if "amount" in r and r["amount"] is not None:
                try:
                    r["amount"] = float(r["amount"])
                except (ValueError, TypeError):
                    pass
        custom_expenses_list = records

with tab2:
    st.caption("Upload your custom CSV file containing date, description, merchant, amount, category, receipt_status:")
    uploaded_file = st.file_uploader("Upload Expense CSV", type=["csv"], key="uploader_csv")
    if uploaded_file is not None:
        try:
            df_uploaded = pd.read_csv(uploaded_file)
            st.success(f"Loaded {len(df_uploaded)} records from '{uploaded_file.name}'. You can edit them below:")
            uploaded_edited = st.data_editor(
                df_uploaded,
                num_rows="dynamic",
                use_container_width=True,
                key="editor_tab2",
            )
            records = uploaded_edited.to_dict(orient="records")
            for r in records:
                if "date" in r and r["date"] is not None:
                    r["date"] = str(r["date"]).split("T")[0]
                if "amount" in r and r["amount"] is not None:
                    try:
                        r["amount"] = float(r["amount"])
                    except (ValueError, TypeError):
                        pass
            custom_expenses_list = records
        except Exception as e:
            st.error(f"Error parsing uploaded CSV: {e}")



# --- Helper Functions ---

def run_agent(request: str, model: str, custom_expenses: list = None, emp_name: str = ""):
    """Execute the agent graph with the given parameters."""
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
    }
    
    try:
        # Stream the graph execution
        result = None
        for event in graph.stream(initial_state, config, stream_mode="values"):
            result = event
        
        # Check if graph is interrupted (waiting for human input)
        current_state = graph.get_state(config)
        if current_state.tasks:
            # Graph paused at an interrupt point
            return None, graph, current_state
        
        return result, graph, None
        
    except GraphInterrupt:
        # Expected — the graph hit an interrupt point
        state = graph.get_state(config)
        return None, graph, state


def resume_agent(graph, response_value: str):
    """Resume the agent after a human-in-the-loop interrupt."""
    config = {"configurable": {"thread_id": st.session_state["thread_id"]}}
    
    try:
        result = None
        for event in graph.stream(Command(resume=response_value), config, stream_mode="values"):
            result = event
        
        # Check if graph hit another interrupt
        current_state = graph.get_state(config)
        if current_state.tasks:
            return None, current_state
        
        return result, None
    except GraphInterrupt:
        state = graph.get_state(config)
        return None, state


def display_workflow_status(statuses: list):
    """Render workflow status messages with appropriate styling."""
    for s in statuses:
        if s.startswith("✓"):
            st.markdown(f'<div class="status-success">{s}</div>', unsafe_allow_html=True)
        elif s.startswith("⚠"):
            st.markdown(f'<div class="status-warning">{s}</div>', unsafe_allow_html=True)
        elif s.startswith("✗"):
            st.markdown(f'<div class="status-error">{s}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="status-info">{s}</div>', unsafe_allow_html=True)


def display_totals(totals: dict):
    """Display expense totals in a styled card."""
    if not totals or not totals.get("category_totals"):
        return
    
    cat_totals = totals["category_totals"]
    grand_total = totals["grand_total"]
    
    st.markdown("### 📊 Expense Summary")
    
    cols = st.columns(min(len(cat_totals), 4))
    for i, (cat, amt) in enumerate(sorted(cat_totals.items())):
        with cols[i % len(cols)]:
            st.metric(label=cat, value=f"₹{amt:,.0f}")
    
    missing_receipt_total = totals.get("missing_receipt_total", 0)
    missing_str = f"  •  Missing receipts: ₹{missing_receipt_total:,.0f}" if missing_receipt_total > 0 else ""
    
    st.markdown(f"""
    <div class="totals-card">
        <h3 style="margin:0; color: #1a237e; font-size: 1.4rem;">Grand Total: ₹{grand_total:,.2f}</h3>
        <div style="margin-top: 0.4rem; color: #424242; font-size: 0.95rem; font-weight: 500;">
            {totals.get('transaction_count', 0)} transactions{missing_str}
        </div>
    </div>
    """, unsafe_allow_html=True)


# --- Execute Button ---
col1, col2 = st.columns([3, 1])
with col1:
    execute_clicked = st.button(
        "🚀 Execute Agent",
        type="primary",
        use_container_width=True,
        disabled=(st.session_state["phase"] not in ("idle", "complete", "error")),
    )

with col2:
    if st.session_state["phase"] != "idle":
        phase_labels = {
            "running": "⏳ Processing...",
            "waiting_missing": "⏸️ Awaiting input",
            "complete": "✅ Complete",
            "error": "❌ Error",
        }
        st.info(phase_labels.get(st.session_state["phase"], ""))

st.divider()

# --- Agent Execution ---
if execute_clicked and user_request.strip():
    st.session_state["phase"] = "running"
    st.session_state["workflow_status"] = []
    st.session_state["error"] = None
    st.session_state["thread_id"] = str(uuid.uuid4())  # Fresh thread
    
    with st.spinner("🤖 Agent is processing your request..."):
        try:
            result, graph, interrupted_state = run_agent(
                request=user_request,
                model=ollama_model,
                custom_expenses=custom_expenses_list,
            )
            
            st.session_state["graph"] = graph
            
            if result is not None:
                # Graph completed without interrupts
                st.session_state["workflow_status"] = result.get("workflow_status", [])
                st.session_state["agent_state"] = result
                st.session_state["pdf_path"] = result.get("pdf_path")
                st.session_state["totals"] = result.get("totals")
                st.session_state["phase"] = "complete"
            elif interrupted_state is not None:
                # Graph was interrupted — need human input
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
            st.error(f"Agent execution failed: {str(e)}")
    
    st.rerun()


# --- Display Workflow Progress ---
if st.session_state["workflow_status"]:
    st.markdown("### 🔄 Workflow Progress")
    display_workflow_status(st.session_state["workflow_status"])
    st.divider()


# --- Human-in-the-Loop: Missing Data ---
if st.session_state["phase"] == "waiting_missing":
    interrupt_data = st.session_state.get("interrupt_data", {})
    
    st.markdown("""
    <div class="hitl-box">
        <h4 style="margin:0; color: #e65100;">⚠️ Human Review Required</h4>
    </div>
    """, unsafe_allow_html=True)
    
    question = interrupt_data.get("question", "Missing data detected. Include or exclude?")
    st.markdown(question)
    
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button("✅ Include (mark as missing)", type="primary", width="stretch"):
            graph = st.session_state["graph"]
            
            with st.spinner("Resuming agent..."):
                try:
                    result, new_interrupted = resume_agent(graph, "include")
                    
                    if result is not None:
                        st.session_state["workflow_status"] = result.get("workflow_status", [])
                        st.session_state["agent_state"] = result
                        st.session_state["pdf_path"] = result.get("pdf_path")
                        st.session_state["totals"] = result.get("totals")
                        st.session_state["phase"] = "complete"
                    elif new_interrupted is not None:
                        state_values = new_interrupted.values
                        st.session_state["workflow_status"] = state_values.get("workflow_status", [])
                        st.session_state["agent_state"] = state_values
                        st.session_state["phase"] = "waiting_missing"
                    
                    st.rerun()
                except Exception as e:
                    st.session_state["error"] = str(e)
                    st.session_state["phase"] = "error"
                    st.rerun()
    
    with col2:
        if st.button("❌ Exclude", width="stretch"):
            graph = st.session_state["graph"]
            
            with st.spinner("Resuming agent..."):
                try:
                    result, new_interrupted = resume_agent(graph, "exclude")
                    
                    if result is not None:
                        st.session_state["workflow_status"] = result.get("workflow_status", [])
                        st.session_state["agent_state"] = result
                        st.session_state["pdf_path"] = result.get("pdf_path")
                        st.session_state["totals"] = result.get("totals")
                        st.session_state["phase"] = "complete"
                    elif new_interrupted is not None:
                        state_values = new_interrupted.values
                        st.session_state["workflow_status"] = state_values.get("workflow_status", [])
                        st.session_state["agent_state"] = state_values
                        st.session_state["phase"] = "waiting_missing"
                    
                    st.rerun()
                except Exception as e:
                    st.session_state["error"] = str(e)
                    st.session_state["phase"] = "error"
                    st.rerun()


# --- Results Section ---
if st.session_state["phase"] in ("complete", "error"):
    
    # Display totals
    if st.session_state.get("totals"):
        display_totals(st.session_state["totals"])
    
    # PDF download
    pdf_path = st.session_state.get("pdf_path")
    if pdf_path and os.path.exists(pdf_path):
        st.markdown("### 📄 Generated Expense Report")
        st.success("✅ Professional Expense Report PDF generated successfully!")
        
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        
        st.download_button(
            label=f"⬇️ Download {os.path.basename(pdf_path)}",
            data=pdf_bytes,
            file_name=os.path.basename(pdf_path),
            mime="application/pdf",
            type="primary",
        )

        # --- Email Report Section ---
        st.divider()
        st.markdown("### 📧 Send Expense Report via Email")
        st.caption(
            "Send the verified PDF report to a manager or finance department with a "
            "custom executive summary and subject line drafted by **Qwen 3**."
        )

        agent_st = st.session_state.get("agent_state", {})
        totals_data = st.session_state.get("totals", {})
        emp_name = agent_st.get("employee_name") or os.getenv("EMPLOYEE_NAME", "Employee")
        s_date = agent_st.get("start_date", "")
        e_date = agent_st.get("end_date", "")
        exp_type = agent_st.get("expense_type", "travel")
        miss_data = agent_st.get("missing_data", [])

        # Auto-generate draft on first report completion if not yet generated
        if not st.session_state.get("email_subject"):
            with st.spinner("🤖 Qwen 3 is drafting the email subject & body..."):
                draft = generate_email_draft(
                    totals=totals_data,
                    employee_name=emp_name,
                    start_date=s_date,
                    end_date=e_date,
                    expense_type=exp_type,
                    missing_data=miss_data,
                    model_name=ollama_model,
                )
                st.session_state["email_subject"] = draft.get("subject", "")
                st.session_state["email_body"] = draft.get("body", "")
                st.session_state["email_source"] = draft.get("source", "qwen3")

        # Email Recipient & Re-draft controls
        col_recip, col_redraft = st.columns([3, 1])
        with col_recip:
            recip_input = st.text_input(
                "📬 Send report to (recipient email)",
                value=st.session_state.get("recipient_email", ""),
                placeholder="Enter recipient email, e.g. manager@company.com",
                key="input_recipient_email",
            )
            st.session_state["recipient_email"] = recip_input

        with col_redraft:
            st.write("")
            st.write("")
            if st.button("✨ Re-draft with Qwen 3", width="stretch"):
                with st.spinner("🤖 Qwen 3 is generating a fresh draft..."):
                    draft = generate_email_draft(
                        totals=totals_data,
                        employee_name=emp_name,
                        start_date=s_date,
                        end_date=e_date,
                        expense_type=exp_type,
                        missing_data=miss_data,
                        model_name=ollama_model,
                    )
                    st.session_state["email_subject"] = draft.get("subject", "")
                    st.session_state["email_body"] = draft.get("body", "")
                    st.session_state["email_source"] = draft.get("source", "qwen3")
                    st.rerun()

        # Email Draft Preview & Editing
        if st.session_state.get("email_subject"):
            badge_html = (
                '<span class="badge-qwen">🤖 Drafted by Qwen 3 (Ollama)</span>'
                if st.session_state.get("email_source") == "qwen3"
                else '<span class="badge-template">📋 Structured Template</span>'
            )
            st.markdown(f"**Email Draft Preview** &nbsp; {badge_html}", unsafe_allow_html=True)

            subj_input = st.text_input(
                "Subject Line",
                value=st.session_state.get("email_subject", ""),
                key="input_email_subject",
            )
            st.session_state["email_subject"] = subj_input

            body_input = st.text_area(
                "Email Body",
                value=st.session_state.get("email_body", ""),
                height=180,
                key="input_email_body",
            )
            st.session_state["email_body"] = body_input

            pdf_size_kb = os.path.getsize(pdf_path) / 1024 if os.path.exists(pdf_path) else 0
            st.caption(f"📎 Attached Report: `{os.path.basename(pdf_path)}` ({pdf_size_kb:.1f} KB) — *PDF will be attached to the email*")

            # Send Email Button
            col_send, _ = st.columns([2, 3])
            with col_send:
                send_email_clicked = st.button("📤 Send Report via Email", type="primary", width="stretch")

            if send_email_clicked:
                to_addr = st.session_state.get("recipient_email", "").strip()
                if not to_addr:
                    st.warning("⚠️ Please provide a recipient email address above before sending.")
                else:
                    with st.spinner("🚀 Dispatching email with attached PDF report via Resend API..."):
                        res = send_email_report(
                            to_email=to_addr,
                            subject=st.session_state.get("email_subject", ""),
                            body=st.session_state.get("email_body", ""),
                            pdf_path=pdf_path,
                            resend_api_key=os.getenv("RESEND_API_KEY", ""),
                            resend_from=os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev"),
                        )
                        st.session_state["email_status"] = res

            # Display delivery status
            status = st.session_state.get("email_status")
            if status:
                if status.get("success"):
                    if status.get("simulated"):
                        st.info(f"ℹ️ {status['message']}")
                    else:
                        st.success(f"{status['message']}")
                else:
                    st.error(f"❌ {status['message']}")
    
    # Error display
    if st.session_state.get("error"):
        st.error(f"⚠️ Error: {st.session_state['error']}")


# --- Agent State Inspector ---
if st.session_state.get("agent_state"):
    with st.expander("🔍 Agent State (Debug)", expanded=False):
        state = st.session_state["agent_state"]
        
        # Display key state fields in a clean format
        display_state = {}
        for key in [
            "user_request", "start_date", "end_date", "expense_type",
            "employee_name", "target_employee", "pdf_path", "error",
        ]:
            if key in state and state[key]:
                display_state[key] = state[key]
        
        st.json(display_state)
        
        # Expense data table
        expenses = state.get("categorized_expenses") or state.get("filtered_expenses", [])
        if expenses:
            st.markdown("**Expense Data:**")
            df = pd.DataFrame(expenses)
            st.dataframe(df, use_container_width=True)


# --- Footer ---
st.divider()
st.markdown(
    "<div style='text-align:center; color:#9e9e9e; font-size:0.85rem;'>"
    "AI Expense Report Agent — Built with LangGraph + Ollama (Qwen3) + Streamlit"
    "</div>",
    unsafe_allow_html=True,
)
