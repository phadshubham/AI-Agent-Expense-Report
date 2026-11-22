# System Responsibility & Failure Mode Accountability Matrix
## AI-Powered Expense Report Management System

---

### 1. Executive RACI Operational Matrix

This RACI matrix defines operational ownership across all functional areas of the platform:
* **R — Responsible**: The member who authors, maintains, and executes the module.
* **A — Accountable**: The sole individual who answers to the examiner/teacher if the component fails.
* **C — Consulted**: The peer engineer who reviews interfaces and dependencies.
* **I — Informed**: Kept up-to-date on state changes and API contracts.

| Functional Architectural Module | Shubham Phad (Lead Agentic AI) | Shubham Mishra (Database Architect) | Paras Salunke (Frontend & Email) | Kaustubh Manjarekar (Compliance & QA) |
| :--- | :---: | :---: | :---: | :---: |
| **LangGraph StateGraph & State Transitions** | **A / R** | C | I | C |
| **NLU Intent Parsing & Dynamic Entity Matching** | **A / R** | I | C | I |
| **Mathematical Integrity Guard (Pandas Math)** | **A / R** | I | I | C |
| **Two-Tier Storage (`expense_memory.db` / `agent_state.db`)** | I | **A / R** | C | I |
| **SHA-256 Dataset Isolation & Query Scoping** | C | **A / R** | C | I |
| **Content-Signature Deduplication Engine (340-Row Fix)**| I | **A / R** | I | C |
| **Streamlit FinTech Application Architecture (`app.py`)** | C | C | **A / R** | C |
| **Interactive Source-of-Truth Table Editor** | I | C | **A / R** | I |
| **Table Health Ribbon & Real-Time Diagnostics** | I | I | **A / R** | I |
| **Autonomous Executive Email Dispatch (Resend API)** | C | I | **A / R** | I |
| **Human-in-the-Loop (HITL) `GraphInterrupt` & Resume** | C | I | C | **A / R** |
| **Auditor Direct Resolution & Managerial Overrides** | I | C | C | **A / R** |
| **Publication-Grade ReportLab Vector PDF Engine** | C | I | I | **A / R** |
| **Comprehensive 324-Test Automated QA Suite** | C | C | C | **A / R** |

---

### 2. Failure Mode Accountability Matrix ("Who Is to Blame If Things Go South?")

When an error, bug, or examination failure occurs, this matrix establishes non-repudiable individual accountability:

```
┌────────────────────────────────────────────────────────────────────────┐
│               SYSTEM FAILURE MODE ACCOUNTABILITY MATRIX                │
├─────────────────────────────────────────────────┬──────────────────────┤
│ Observed System Failure / Bug                   │ Person Accountable   │
├─────────────────────────────────────────────────┼──────────────────────┤
│ 1. Math totals hallucinated or wrong            │ Shubham Phad         │
│ 2. Infinite loop or agent state cycle failure   │ Shubham Phad         │
│ 3. Misspelled employee name not matched         │ Shubham Phad         │
│ 4. Duplicate rows created (e.g. 340-row bug)    │ Shubham Mishra       │
│ 5. Data bleeding between Dataset A and B        │ Shubham Mishra       │
│ 6. SQLite database schema corruption / crash    │ Shubham Mishra       │
│ 7. Streamlit UI crash, blank screen, rerun loop │ Paras Salunke        │
│ 8. Table editor edits lost upon saving          │ Paras Salunke        │
│ 9. Table Health Ribbon shows wrong spend total  │ Paras Salunke        │
│ 10. Executive email fails to send / Resend error│ Paras Salunke        │
│ 11. Policy violation silently bypasses review   │ Kaustubh Manjarekar  │
│ 12. Managerial override not saved in memory     │ Kaustubh Manjarekar  │
│ 13. PDF has broken formatting or wrong badge    │ Kaustubh Manjarekar  │
│ 14. Automated tests fail in pytest              │ Kaustubh Manjarekar  │
└─────────────────────────────────────────────────┴──────────────────────┘
```

#### Detailed Breakdown of Failure Modes:

#### Scenario A: Arithmetic Discrepancy or Calculation Failure
* **Failure**: The expense report claims total spend is ₹620,000 when the actual row sum is ₹609,550, or category subtotals do not match.
* **Who is to Blame**: **Shubham Phad** (Lead Agentic AI Engineer)
* **Root Cause Responsibility**: Agent 3 allowed an unverified LLM number into the state, or `calculate_deterministic_summary()` in `tools/calculation_tools.py` was bypassed.
* **Required Fix**: Ensure `calculate_deterministic_summary` calculates aggregates exclusively with Pandas vector sums.

#### Scenario B: Row Duplication (e.g. 170 Rows Double to 340)
* **Failure**: Re-running an analysis or re-uploading an existing file increases the transaction count from 170 to 340.
* **Who is to Blame**: **Shubham Mishra** (Database Architect)
* **Root Cause Responsibility**: The content-signature pool in `save_expenses()` in `tools/memory_tools.py` failed to match existing tuples `(date, employee, description, merchant, amount)`.
* **Required Fix**: Verify that `existing_pool` is populated before insertion and canonical `record_id`s are returned.

#### Scenario C: Data Contamination Between Datasets
* **Failure**: User uploads Dataset B, but reports or memory tabs display expenses from Dataset A.
* **Who is to Blame**: **Shubham Mishra** (Database Architect)
* **Root Cause Responsibility**: A database retrieval function in `tools/memory_tools.py` ran an un-scoped query (`SELECT * FROM expenses_v2`) without `WHERE dataset_id = ?`.
* **Required Fix**: Re-assert the `dataset_id` foreign key check on all SQL queries.

#### Scenario D: Streamlit UI Crash or Stale Widget Values
* **Failure**: User modifies an amount in the table editor, but clicking "Execute Workflow" reverts the value to the original CSV content.
* **Who is to Blame**: **Paras Salunke** (FinTech Frontend Engineer)
* **Root Cause Responsibility**: Dynamic widget keys in `st.data_editor` were not incremented with `editor_version`, or `st.session_state["custom_expenses_list"]` was overwritten by an uncached rerun.
* **Required Fix**: Synchronize `st.session_state["custom_expenses_list"]` with `edited_df` before invoking the agent.

#### Scenario E: Executive Email Dispatch Failure
* **Failure**: Clicking "Dispatch Executive Email" returns an error, or the email draft contains garbled formatting.
* **Who is to Blame**: **Paras Salunke** (Autonomous Communications Engineer)
* **Root Cause Responsibility**: `tools/email_tools.py` failed to catch a missing `RESEND_API_KEY`, or payload formatting in `send_expense_email()` was malformed.
* **Required Fix**: Check API key environment variables and verify Qwen 3 HTML briefing synthesis.

#### Scenario F: Silent Policy Bypass (Zero Human-in-the-Loop Escalation)
* **Failure**: An employee submits a ₹3,000 meal expense (> ₹1,500 limit) with no receipt, but the system marks the report "100% Compliant" and generates a PDF without stopping.
* **Who is to Blame**: **Kaustubh Manjarekar** (Compliance & QA Lead)
* **Root Cause Responsibility**: `detect_compliance_issues()` in `tools/validation_tools.py` failed to flag the transaction, or the `GraphInterrupt` conditional edge in `agent.py` was skipped.
* **Required Fix**: Ensure `check_validation_status` routes to `END` with `needs_human_review = True` whenever unresolved violations exist.

#### Scenario G: Vector PDF Layout Failure or Broken Audit Badge
* **Failure**: The PDF report has overlapping text, cut-off tables, or displays an emerald "100% COMPLIANT" badge when exceptions were authorized.
* **Who is to Blame**: **Kaustubh Manjarekar** (Document Vector Systems Lead)
* **Root Cause Responsibility**: `generate_vector_expense_pdf()` in `tools/pdf_tools.py` failed to evaluate `is_compliant` flags or miscalculated column widths in ReportLab.
* **Required Fix**: Recalculate flowable widths against printable page bounds (`523.28 pt`).

#### Scenario H: Automated Test Suite Regression
* **Failure**: Running `pytest` produces errors or failures instead of `324 passed`.
* **Who is to Blame**: **Kaustubh Manjarekar** (QA Lead)
* **Root Cause Responsibility**: Test assertions in `tests/` were not kept in sync with code updates, or regression tests were not run prior to committing.
* **Required Fix**: Execute `pytest -q` and fix breaking test fixtures.

---

### 3. Live Examination / Viva Defense Protocol

During project evaluation or professor questioning, follow this protocol:

1. **If asked about Agentic AI, LangGraph, or NLU**:
   * **Shubham Phad** speaks.
   * *Key talking points*: LangGraph StateGraph, Qwen 3 + regex fallback, RapidFuzz entity resolution, Pandas math guard.

2. **If asked about SQLite, Database Schemas, or Deduplication**:
   * **Shubham Mishra** speaks.
   * *Key talking points*: Two-tier storage (`expense_memory.db` vs `agent_state.db`), SHA-256 dataset isolation, content-signature hash pool fixing the 340-row bug.

3. **If asked about UI/UX, AgGrid Table Editing, or Email Dispatch**:
   * **Paras Salunke** speaks.
   * *Key talking points*: Streamlit reactive session state, Table Health Ribbon, source-of-truth table editor, Resend API email integration.

4. **If asked about Human-in-the-Loop, Vector PDF Badges, or 324 Tests**:
   * **Kaustubh Manjarekar** speaks.
   * *Key talking points*: `GraphInterrupt` and `Command(resume)`, ReportLab vector typography with audit badges, 324-test 4-tier verification suite.
