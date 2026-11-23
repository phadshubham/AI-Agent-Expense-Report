# Individual Contributions

---

### 1. Shubham Phad (ADT23SOCB1106)

* **LangGraph Multi-Agent Orchestration**:
  * Designed and built the compiled `StateGraph` workflow coordinating the execution handoffs between Agent 1, Agent 2, and Agent 3.
  * Implemented the centralized state schema (`ExpenseAgentState`) in `state.py` to pass data, audit issues, and calculation results between nodes.
  * Configured conditional routing logic (`check_zero_records` and `check_validation_status`) to govern state transitions, zero-record aborts, and human review branches.

* **Agent 1: Expense Analysis Engine**:
  * Developed the natural-language intent parser in `tools/expense_tools.py` combining local Ollama Qwen 3 inference with a regex fallback parser.
  * Implemented dynamic fuzzy entity resolution using `RapidFuzz` to match typed employee names against the active dataset registry.
  * Built date normalization logic to convert relative expressions (e.g., *"last month"*, *"August 2026"*) into strict calendar bounds `[start_date, end_date]`.
  * Added boundary diagnostics to prevent silent failures when query criteria fall outside dataset date coverage.

* **Agent 2: Compliance & Policy Auditor**:
  * Programmed the compliance evaluation rules in `tools/validation_tools.py` to audit expenses against corporate caps (₹1,500 single meal, ₹5,000 daily spend, ₹25,000 travel).
  * Built automatic detection for missing receipts, negative amounts, null values, and out-of-policy claims.

* **Agent 3: Deterministic Arithmetic Core**:
  * Created the `Mathematical Integrity Guard` in `tools/calculation_tools.py` using vectorized Pandas operations (sum, count, category subtotals, employee aggregates).
  * Enforced zero generative LLM math to eliminate arithmetic hallucination.

* **Primary Code Files Authored**:
  * `agent.py`
  * `state.py`
  * `tools/expense_tools.py`
  * `tools/validation_tools.py`
  * `tools/calculation_tools.py`

---

### 2. Shubham Mishra (ADT23SOCB1110)

* **Two-Tier Storage Architecture**:
  * Implemented the storage decoupling between persistent business data (`data/expense_memory.db`) and runtime workflow state checkpoints (`.checkpoints/agent_state.db`).
  * Structured the production relational schema across `datasets`, `expenses_v2`, `validation_issues_v2`, `report_runs_v2`, `audit_events`, and `import_batches`.

* **Cryptographic Dataset Isolation**:
  * Implemented SHA-256 file hashing to compute unique fingerprints for every uploaded CSV file.
  * Assigned distinct `dataset_id` identifiers to isolate all stored transactions, validation issues, prompt history, and report snapshots.
  * Scoped all database query functions in `tools/memory_tools.py` with `WHERE dataset_id = ?` to prevent data leakage between different datasets.

* **Content-Signature Deduplication Engine**:
  * Diagnosed and fixed the 340-row duplication bug where re-running workflows duplicated rows.
  * Developed the content-hash signature pool:
    $$\text{ContentHash} = \text{SHA-256}(\text{date} \parallel \text{employee} \parallel \text{description} \parallel \text{merchant} \parallel \text{amount})$$
  * Ensured repeated runs reuse canonical record IDs, preserving the exact 170-row count and ₹609,550.00 total spend.

* **Audit Memory Persistence**:
  * Created database persistence for managerial review decisions (`accept_exception`, `exclude`, `correct`) in `validation_issues_v2`.
  * Built immutable historical run logging in `report_runs_v2` for reproducible report snapshots.

* **Primary Code Files Authored**:
  * `tools/memory_tools.py`
  * `data/expense_memory.db`
  * `tests/test_milestone1_db.py`

---

### 3. Paras Salunke (ADT23SOCB0692)

* **Streamlit Application Interface**:
  * Developed the core user interface in `app.py` across 4 operational tabs (Executive Workspace, Prompt & Report History, SQLite Memory & Ingestion, Compliance & Validation).
  * Styled the application using a custom theme with deep navy/indigo headers, slate surfaces, and clean responsive containers.

* **Interactive Source-of-Truth Table Editor**:
  * Integrated `st.data_editor` as the primary live interface for modifying, adding, and deleting expense transactions.
  * Implemented dynamic widget keying (`key=f"editor_{dataset_id}_{version}"`) to prevent loss of user edits during Streamlit reruns.
  * Created the Save Changes handler to update active dataset versions and sync modifications directly to SQLite memory.

* **Real-Time Table Health & Diagnostics Ribbon**:
  * Built the dynamic financial health ribbon that recalculates live metrics on every user interaction:
    * Active transaction count (170 rows)
    * Live monetary spend (₹609,550.00)
    * Missing receipt count (5 missing)
    * Null amount count (0 nulls)

* **Multi-Agent Visual Telemetry**:
  * Designed the Multi-Agent Collaboration Stages monitor tracking live status for Agent 1, Agent 2, and Agent 3.
  * Built the Chronological Activity & Audit Log displaying sequential execution traces, retrieval counts, and entity match scores.

* **Autonomous Executive Email Dispatch**:
  * Authored `tools/email_tools.py` to generate and send executive expense summaries.
  * Integrated local Ollama Qwen 3 (with fallback templates) to draft structured executive briefings.
  * Integrated the Resend API to dispatch formatted HTML emails with links to generated PDF reports.

* **Primary Code Files Authored**:
  * `app.py`
  * `tools/email_tools.py`
  * Application CSS styling and UI components

---

### 4. Kaustubh Manjarekar (ADT23SOCB0510)

* **Human-in-the-Loop (HITL) Review Flow**:
  * Implemented LangGraph `interrupt()` handling in the workflow to halt execution whenever policy violations or missing receipts are detected.
  * Handled workflow resumption using `Command(resume={"action": action, ...})` to apply human decisions without losing graph state.

* **Auditor Direct Resolution Console**:
  * Built the managerial resolution controls in the Compliance tab allowing auditors to:
    * `accept_exception`: Approve out-of-policy expenses with documented managerial justifications.
    * `exclude`: Strip non-compliant items from subsequent reports and aggregations.
    * `correct`: Fix invalid transaction values directly in persistent storage.
  * Bound resolution actions to `audit_events` with timestamps and reviewer IDs for audit compliance.

* **Publication-Grade Vector PDF Generation Engine**:
  * Built the PDF compilation engine in `tools/pdf_tools.py` using ReportLab flowables.
  * Implemented official compliance badges (emerald `100% COMPLIANT` vs amber `APPROVED WITH EXCEPTIONS`).
  * Programmed dynamic table pagination, automatic column wrapping, summary metric cards, and running headers.

* **Automated QA Verification Suite**:
  * Authored the entire 324-test automated test suite across 4 verification tiers:
    * Tier 1: SQLite Storage & Multi-Dataset Isolation (98 tests)
    * Tier 2: Vector PDF & Mathematical Integrity Guard (74 tests)
    * Tier 3: LangGraph Orchestration & HITL Workflows (82 tests)
    * Tier 4: Edge Cases, Null Resilience & Idempotence (70 tests)
  * Verified 100% test pass rate in under 11 seconds (`324 passed in 10.68s`) with 0 regressions.

* **Primary Code Files Authored**:
  * `tools/pdf_tools.py`
  * `tests/test_e2e_tier1_features.py`
  * `tests/test_e2e_tier2_boundaries.py`
  * `tests/test_e2e_tier3_combinations.py`
  * `tests/test_e2e_tier4_scenarios.py`
  * `tests/test_e2e_tier5_adversarial.py`
  * `tests/test_tools.py`
  * `scripts/generate_project_report.py`
