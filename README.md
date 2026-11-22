# 📊 AI Expense Report Agent (Autonomous Multi-Agent FinTech Platform)

An **Agentic AI** system that autonomously processes corporate expenses, validates compliance documentation, executes Human-in-the-Loop review, coordinates three specialized collaborating agents, persists historical records in SQLite, and generates publication-grade PDF reports — all from free-form natural language requests.

> *"Generate my travel expense report for last month."*  
> *"Generate all expenses report for Ravi Kumar."*  
> *"Travel expenses for Priya Sharma in August 2026."*

---

## ✨ Key Capabilities

- **Persistent SQLite Memory Architecture (`data/expense_memory.db`)**:
  - Independent database with schema v2 for long-term storage of expense records, dataset master registry, version history, SHA-256 cryptographic deduplication, historical validation findings, and generated report runs.
  - Strictly separated from `.checkpoints/agent_state.db` (which is used exclusively for LangGraph workflow execution checkpoints).
- **Multi-Agent Collaboration Engine (LangGraph StateGraph)**:
  - **Expense Analysis Agent**: Interprets natural language requests, interfaces with memory, dynamically matches employees without substring collision, deterministically filters records, and categorizes transactions.
  - **Validation Agent**: Audits compliance (receipt completeness, non-positive or null amounts, missing dates, duplicate transactions) and records structured findings to SQLite memory.
  - **Report Generation Agent**: Enforces validation integrity guards, computes deterministic totals with Pandas, renders publication-grade ReportLab PDFs with validation status badges, and archives report-run metadata.
- **Dataset Isolation & Interactive Data Editor**:
  - Manage multiple isolated datasets simultaneously (uploaded CSVs, master dataset, sample datasets).
  - Inline table editing via Streamlit with full support for adding rows, editing 8 distinct fields, deleting records, and saving versions (`v1`, `v2`, etc.).
- **Human-in-the-Loop (HITL) Review & Memory Synchronization**:
  - Pauses execution via LangGraph `interrupt()` when compliance discrepancies are flagged.
  - Reviewer can **Authorize Documented Exceptions** (status: *Reviewed with Exceptions*), **Exclude Flagged Items** (status: *Clear*), **Input Missing Values** (amount, date, receipt status), or **Authorize/Exclude Individual Records**.
  - **Persistent Decision Memory**: Auditor resolutions made in the Compliance Audit tab or in the HITL review are saved in SQLite memory. When you run the workflow again, the system remembers your view and **continues straight to report generation without interrupting again**.
- **Report Validation Status Model**:
  - `Clear`: All validation checks passed, zero unresolved discrepancies.
  - `Reviewed with Exceptions`: Proceeded under authorized managerial exception policy with complete audit notes.
  - `Needs Human Review`: Blocked from final approval due to unresolved issues.
- **Interactive Streamlit Web UI (Enterprise FinTech Design System)**:
  - Built with a modern, high-contrast **Crisp Light Theme** (Stripe/Ramp/Mercury aesthetic) featuring tabular financial typography, live multi-agent stage tracking cards, Human-in-the-Loop audit modal, prompt formulation, interactive data editing, and 4 dedicated application views.
  - Persistent design guidelines established in [`task.md`](task.md) and [`.agent/rules/design-context.md`](.agent/rules/design-context.md).
- **AI Email Drafting & Dispatch**:
  - Qwen 3 drafting via local Ollama with fallback templates and live Resend API / simulation dispatch.

---

## 🏗️ Multi-Agent Architecture

```
USER REQUEST (Natural Language)
        ↓
   STREAMLIT UI
        ↓
  LANGGRAPH AGENT GRAPH (StateGraph + SQLite Checkpoints)
        ↓
┌────────────────────────────────────────────────────────────────────────┐
│ 🤖 AGENT 1: EXPENSE ANALYSIS AGENT                                     │
│ • Natural Language Intent Extraction (Qwen 3 LLM / Regex Fallback)     │
│ • Memory Sync & Deduplicated Ingestion (data/expense_memory.db)        │
│ • Deterministic Filtering (Date range, Employee, Category, Location)   │
│ • Zero State Leakage & Dynamic Employee Matching                       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    ↓ (Structured Expense Analysis)
┌────────────────────────────────────────────────────────────────────────┐
│ 🛡️ AGENT 2: VALIDATION AGENT                                           │
│ • Receipt Completeness & Amount Verification                           │
│ • Duplicate Transaction & Missing Field Auditing                       │
│ • Persistent Memory Inspection: Recognizes Pre-Authorized Exceptions   │
│ • Persistence of Structured Issues into SQLite Memory                  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    ↓
                 [Unresolved Discrepancies?]
                        /               \
                    YES                  NO (or Pre-Authorized)
                    /                     \
┌───────────────────────────┐              \
│ 👤 HUMAN-IN-THE-LOOP      │               \
│ • Exclude flagged items   │                \
│ • Accept exceptions       │                 \
│ • Input missing values    │                  \
└─────────────┬─────────────┘                   \
              \                                 /
               \───────► [All Clear/Reviewed] ◄/
                                ↓
┌────────────────────────────────────────────────────────────────────────┐
│ 📑 AGENT 3: REPORT GENERATION AGENT                                    │
│ • Integrity Guard: Refuses silent approval of unresolved issues        │
│ • Deterministic Financial Totals & Subtotals (Pandas)                  │
│ • PDF Generation with Validation Badges (ReportLab)                    │
│ • Archive Report Run to SQLite Memory                                  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    ↓
                    DOWNLOADABLE EXPENSE REPORT PDF
                     (Single or Multi-Employee PDF)
```

---

## 📋 Prerequisites

1. **Python 3.10+** (tested with Python 3.13)
2. **Ollama** — Local LLM runtime ([Download Ollama](https://ollama.com/download))

---

## 🚀 Setup & Quickstart

### Step 1: Install & Pull Ollama Model

```bash
ollama pull qwen3:4b
```

Verify it is running:
```bash
ollama list
```

### Step 2: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 3: Configure Environment

Copy `.env.example` to `.env`:
```bash
copy .env.example .env
```

Configuration variables:
```env
OLLAMA_MODEL=qwen3:4b
OLLAMA_BASE_URL=http://localhost:11434
EXPENSE_CSV_PATH=data/expenses.csv
EXPENSE_MEMORY_DB_PATH=data/expense_memory.db
RESEND_API_KEY=
```

### Step 4: Run the Application

```bash
streamlit run app.py
```

The app opens automatically at `http://localhost:8501`.

---

## 🎯 Feature Demonstrations

### 1. Persistent SQLite Memory
1. **Database Separation**: [`data/expense_memory.db`](data/expense_memory.db) (business data & issues) vs [`.checkpoints/agent_state.db`](.checkpoints/agent_state.db) (LangGraph thread checkpoints).
2. **Deduplication & Safety**:
   - Go to tab **"🧠 Persistent SQLite Memory & Ingestion"**.
   - Ingesting the master CSV repeatedly will skip identical records rather than creating duplicates (proving SHA-256 batch deduplication).
3. **Historical Retrieval Without CSV Uploads**:
   - Enter: `"Generate travel expense report for last month"` or `"Generate all expenses report for Ravi Kumar"`.
   - The agent retrieves the active dataset from persistent memory and filters accurately across dates.

### 2. Multi-Agent Collaboration & Integrity Guard
1. **Three Discrete Agents**:
   - **Expense Analysis Agent**: Interprets natural language, retrieves from memory, dynamically matches employee entities, and filters records.
   - **Validation Agent**: Audits receipt completeness, non-zero amounts, and duplicate transactions; persists structured issues to SQLite.
   - **Report Generation Agent**: Enforces validation guards (refuses silent approval of unresolved issues), computes deterministic Pandas math, renders ReportLab PDF with validation status badges, and archives the run.
2. **Audit Status Badges in Final Report**:
   - Green: `VERIFIED & CLEAR` (100% compliant).
   - Amber: `REVIEWED WITH DOCUMENTED EXCEPTIONS` (Approved with recorded reviewer notes).
   - Red: `NEEDS HUMAN REVIEW` (Unresolved discrepancies).

### 3. Compliance & Auditor Direct Resolution
1. Go to tab **"🛡️ Compliance & Validation Issues"**.
2. Select an issue and choose:
   - `❌ Exclude from Counting & Reports`: Marks `is_excluded = 1` and excludes the transaction from financial totals.
   - `✅ Authorize Managerial Exception`: Documents authorized managerial exception notes.
3. When you run the workflow again, **the agent remembers your resolution and does NOT stop for approval** — it automatically proceeds straight to report generation!

---

## 🎨 Enterprise FinTech Design System & UI Architecture

The application interface is crafted under the **Teach-Impeccable** design context, tailored specifically for **Corporate Finance Managers and Compliance Auditors**:

1. **Crisp Light Theme & Tabular Typography**:
   - Canvas: Soft crisp slate (`#f8fafc`) with clean white card surfaces (`#ffffff`) and subtle borders (`#e2e8f0`).
   - Brand Anchor: Deep Navy / Indigo (`#1a237e`, `#0f172a`).
   - Strict `font-variant-numeric: tabular-nums` across all currency values (`₹`), dates, and metrics for scannability.
2. **Four Dedicated Workspaces**:
   - **📊 Executive Workspace & Execution**: Interactive table editor, free-form natural language prompt, active multi-agent stage cards, chronological audit log, Human-in-the-Loop exception console, financial summary ribbon, and Qwen 3 email console.
   - **📜 Prompt & Report Run History**: Searchable and filterable archive of past report runs from SQLite `report_runs_v2` with actions to **Load Prompt**, **Re-run**, and **Download PDF**.
   - **🧠 Persistent SQLite Memory & Ingestion**: Real-time memory counters, cryptographic SHA-256 deduplication ingestion trigger, and interactive raw table inspector.
   - **🛡️ Compliance & Validation Issues**: Dedicated auditor workspace tracking open discrepancies across the company with one-click managerial exception approval or exclusion.
3. **Semantic Status Indicators**:
   - `VERIFIED & CLEAR`: Emerald Green (`#059669` / `#ecfdf5`).
   - `REVIEWED WITH EXCEPTIONS`: Amber (`#d97706` / `#fffbeb`).
   - `NEEDS HUMAN REVIEW`: Crimson (`#dc2626` / `#fef2f2`).
   - `PROCESSING`: Blue (`#2563eb` / `#eff6ff`).

---

## 🧪 Running the Test Suite

All test suites live consolidated inside the [`tests/`](tests/) folder and run locally using isolated temporary SQLite databases without requiring external APIs:

```bash
# Run the entire test suite (324 tests across all tiers & milestones)
pytest

# Run specific test modules:
pytest tests/test_milestone1_db.py           # Database migration, schema triggers, dataset isolation
pytest tests/test_milestone2_filters.py      # Canonical filters, employee matching, location aliasing
pytest tests/test_milestone3_compliance.py   # Auditor direct resolution & persistent HITL memory
pytest tests/test_e2e_tier1_features.py      # Core end-to-end features
pytest tests/test_e2e_tier5_adversarial.py   # Adversarial hardening & fuzzing
```

---

## 📁 Project Structure

```
AI Agent Expense report/
├── app.py                      # Streamlit UI: Multi-agent tracking, table editor, HITL review, memory console
├── agent.py                    # LangGraph workflow connecting the 3 collaborating agents
├── state.py                    # AgentState and ParsedFilters TypedDict definitions
├── tools/
│   ├── memory_tools.py         # SQLite persistent memory v2, dataset registry, deduplication, reviewer decisions
│   ├── expense_tools.py        # CSV loading, currency cleaning, date/employee/location/category filtering
│   ├── validation_tools.py     # Compliance audit, category inference, single-record revalidation
│   ├── calculation_tools.py    # Deterministic financial math & subtotals (Pandas)
│   ├── pdf_tools.py            # ReportLab PDF engine with validation status badges
│   └── email_tools.py          # Qwen 3 email draft generation & Resend API dispatch
├── tests/                      # Consolidated automated test suite (324 tests)
│   ├── test_milestone1_db.py
│   ├── test_milestone2_filters.py
│   ├── test_milestone3_compliance.py
│   ├── test_e2e_tier1_features.py
│   ├── test_e2e_tier2_boundaries.py
│   ├── test_e2e_tier3_combinations.py
│   ├── test_e2e_tier4_scenarios.py
│   ├── test_e2e_tier5_adversarial.py
│   ├── test_memory_and_agents.py
│   ├── test_tools.py
│   └── test_email_tools.py
├── data/
│   ├── expense_memory.db       # Persistent business-data database (expenses_v2, datasets, audit_events)
│   ├── expenses.csv            # Master dataset (170 entries across 5 months & 5 employees)
│   └── sample_csvs/            # Additional scenario datasets
├── .checkpoints/
│   └── agent_state.db          # LangGraph workflow state checkpointer
├── reports/                    # Generated output PDF expense reports
├── requirements.txt            # Python dependencies
├── pytest.ini                  # Pytest configuration pointing to tests/
├── task.md                     # Teach-Impeccable persistent design context & principles
├── PROJECT_INFO.md             # Complete technical architecture & developer blueprint
├── CSV_PROMPT_GUIDE.md         # Dataset guide & prompt cookbook
└── README.md                   # Project documentation
```

---

## 🛡️ Database Separation & Resetting

- **Business Memory Database**: [`data/expense_memory.db`](data/expense_memory.db)
  - Contains persistent tables: `datasets`, `expenses_v2`, `validation_issues_v2`, `report_runs_v2`, `import_batches`, and `audit_events`.
- **Workflow Checkpoint Database**: [`.checkpoints/agent_state.db`](.checkpoints/agent_state.db)
  - Contains LangGraph thread checkpoints used solely to pause and resume agent workflows during HITL reviews.

**Safe Database Reset**:
To reset the development/test memory database without affecting source CSV data:
```bash
del data\expense_memory.db
```
The database will automatically reinitialize its schema on the next run.
