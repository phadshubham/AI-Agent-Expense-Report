# Role Dossier: Paras Salunke (ADT23SOCB0692)
## FinTech Frontend & Autonomous Communications Engineer

---

### 1. Executive Summary & Core Identity
As the **FinTech Frontend & Autonomous Communications Engineer**, you built the **live user-facing platform** (`app.py`), the **Interactive Source-of-Truth Data Editor**, the **Table Health Ribbon**, and the **Autonomous Executive Email Dispatch Console** (`tools/email_tools.py`).

If the teacher asks: *"How does the user interact with the system?", "Where do they edit records?", "How do the agent stages update in real time?"* or *"How are executive emails drafted and dispatched?"* — **You are the one who answers.**

---

### 2. Modules & Core Architecture Owned

#### A. Streamlit FinTech UI Architecture (`app.py`)
* Implemented the corporate visual personality: **Authoritative, Crisp, Trustworthy** using a deep navy/indigo identity (`#1a237e`), slate surfaces (`#f8fafc`), emerald successes (`#059669`), and amber warnings (`#d97706`).
* Structured the platform into four intuitive, responsive operational tabs:
  1. `Executive Workspace & Execution`: Data ingestion, interactive table editor, prompt formulation, and multi-agent execution results.
  2. `Prompt & Report Run History`: Historical report repository with dataset-specific filtering and prompt replay.
  3. `Persistent SQLite Memory & Ingestion`: Transparent database inspection, table health metrics, and raw SQLite explorer.
  4. `Compliance & Validation Issues`: Compliance issue tracker with direct auditor resolution capabilities.

#### B. Interactive Expense Data Editor (Source of Truth)
* Integrated `st.data_editor` as the **active source of truth**, not just a passive preview.
* Allowed users to:
  * Edit amounts, categories, dates, and receipt statuses in-place.
  * Add new rows or delete invalid transactions.
  * Retain edits without stale session-state resets on Streamlit reruns.
* Built the **Save Changes** action that updates the active dataset, increments the version number (e.g. `v1 -> v2`), and automatically syncs changes to SQLite memory.

#### C. Live Table Health & Diagnostics Ribbon
* Built a high-performance financial health ribbon above the table editor.
* Recalculates metrics dynamically in real time:
  * **Active Transactions**: `170 Transactions`
  * **Live Total Spend**: `Live Total: ₹609,550.00`
  * **Missing Receipts**: `Missing Receipts: 5`
  * **Null Amounts**: `Null Amounts: 0`
* Gives the financial auditor instant visibility into dataset integrity before triggering any agent execution.

#### D. Multi-Agent Telemetry & Audit Dashboard
* Created the **Multi-Agent Collaboration Stages** visual card monitor tracking Agent 1 (Expense Analysis), Agent 2 (Validation), and Agent 3 (Report Generation).
* Built the **Chronological Activity & Audit Log** displaying sequential handoffs, dynamic employee fuzzy match scores, database retrieval counts, and validation checks.

#### E. Autonomous Executive Email Dispatch Console (`tools/email_tools.py`)
* Designed the executive email dispatch module that allows one-click delivery of verified financial reports to corporate executives.
* Built **`draft_expense_email()`**: Uses local **Ollama Qwen 3** (with a robust deterministic fallback) to generate a concise, professional executive briefing highlighting total spend, employee name, compliance status, and policy exceptions.
* Built **`send_expense_email()`**: Integrated with the **Resend Transactional API** to securely dispatch formatted HTML/text emails with clickable links to generated vector PDFs.

---

### 3. Critical Code You Authored & Must Walk Through

#### A. Interactive Table Editor & Health Ribbon (`app.py`)
```python
# Real-Time Health Ribbon calculation
total_tx = len(st.session_state["custom_expenses_list"])
total_spend = sum(float(x.get("amount", 0.0) or 0.0) for x in st.session_state["custom_expenses_list"])
missing_rcpts = sum(1 for x in st.session_state["custom_expenses_list"] if str(x.get("receipt_status", "")).lower() == "missing")
null_amts = sum(1 for x in st.session_state["custom_expenses_list"] if x.get("amount") is None or str(x.get("amount", "")).strip() == "")

# Render Health Ribbon
st.markdown(f"""
<div class="health-ribbon">
    <span>📊 <b>{total_tx}</b> Transactions in Active Copy</span>
    <span>💰 Live Total: <b>₹{total_spend:,.2f}</b></span>
    <span>⚠️ Missing Receipts: <b>{missing_rcpts}</b></span>
    <span>🚨 Null Amounts: <b>{null_amts}</b></span>
</div>
""", unsafe_allow_html=True)

# Interactive Source-of-Truth Editor
edited_df = st.data_editor(
    df,
    num_rows="dynamic",
    use_container_width=True,
    key=f"editor_{st.session_state.get('active_dataset_id', 'default')}_{st.session_state.get('editor_version', 1)}",
    column_config={
        "amount": st.column_config.NumberColumn("amount", format="₹%.2f"),
        "date": st.column_config.DateColumn("date"),
        "receipt_status": st.column_config.SelectboxColumn("receipt_status", options=["Available", "Missing"])
    }
)
```

#### B. Executive Email Synthesis & Resend Dispatch (`tools/email_tools.py`)
```python
import os
import requests

def send_expense_email(recipient_email: str, subject: str, html_body: str, pdf_path: str = None) -> dict:
    """
    Dispatches verified executive expense reports via the Resend API.
    """
    resend_api_key = os.getenv("RESEND_API_KEY", "").strip()
    if not resend_api_key:
        return {"status": "error", "message": "RESEND_API_KEY is not configured."}

    payload = {
        "from": "Expense Audit AI <onboarding@resend.dev>",
        "to": [recipient_email],
        "subject": subject,
        "html": html_body
    }

    headers = {
        "Authorization": f"Bearer {resend_api_key}",
        "Content-Type": "application/json"
    }

    response = requests.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=10)
    if response.status_code in [200, 201]:
        return {"status": "success", "data": response.json()}
    else:
        return {"status": "error", "message": response.text}
```

---

### 4. Likely Teacher / Viva Questions & Model Answers

* **Q1: "Why is the interactive table editor the source of truth rather than a raw CSV file?"**
  * **Your Answer**: *"In a corporate setting, financial analysts frequently need to correct a missing receipt status or adjust a merchant name before submitting a report. By making the interactive table editor the active source of truth, user edits immediately propagate into the active dataset in SQLite. All downstream validation and report generation operate directly on the user's latest edited records."*

* **Q2: "How do you prevent Streamlit widget keys from causing state resets on reruns?"**
  * **Your Answer**: *"Streamlit re-executes the script from top to bottom on user interaction. To prevent stale editor data or unwanted resets, I bound the `st.data_editor` key to a compound identifier containing the active `dataset_id` and an incrementing `editor_version`: `key=f'editor_{dataset_id}_{version}'`. When the user saves changes or switches datasets, we increment the version, safely refreshing the UI without state collisions."*

* **Q3: "How does the executive email feature work?"**
  * **Your Answer**: *"In `tools/email_tools.py`, once Agent 3 generates the verified report, we call `draft_expense_email`. It passes the financial summary (total spend, transaction count, employee name, and compliance status) to Ollama Qwen 3 to draft an executive briefing. The user reviews the drafted email in the UI and clicks 'Dispatch Executive Email', which calls the Resend API over HTTPS to deliver the email."*
