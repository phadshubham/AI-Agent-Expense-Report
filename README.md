# 📊 AI Expense Report Agent (Multi-Agent System & Persistent Memory)

An **Agentic AI** system that autonomously processes travel expenses, validates missing documentation via Human-in-the-Loop review, coordinates three specialized collaborating agents, persists historical records in SQLite, and generates publication-grade PDF reports — all from free-form natural language requests.

> *"Generate my travel expense report for last month."*  
> *"Generate August 2026 report for Priya Sharma."*

---

## ✨ Key Features

- **Unit III: Persistent SQLite Memory (`data/expense_memory.db`)**:
  - Independent database for long-term storage of expense records, import batches with cryptographic deduplication, historical validation findings, and generated report runs.
  - Distinct from `.checkpoints/agent_state.db` (which is used exclusively for LangGraph workflow state persistence).
- **Unit IV: Multi-Agent Collaboration (LangGraph StateGraph)**:
  - **Expense Analysis Agent**: Interprets natural language requests, interfaces with memory, dynamically matches employees, deterministically filters records, and categorizes transactions.
  - **Validation Agent**: Audits compliance (receipt completeness, non-positive amounts, missing dates, duplicate transactions) and records structured findings to SQLite memory.
  - **Report Generation Agent**: Enforces validation integrity guards, computes deterministic totals with Pandas, renders publication-grade ReportLab PDFs with validation status badges, and archives report-run metadata.
- **Human-in-the-Loop (HITL) Review**:
  - Pauses execution via LangGraph `interrupt()` when compliance discrepancies are flagged.
  - Reviewer can **Authorize Documented Exceptions** (status: *Reviewed with Exceptions*), **Exclude Flagged Items** (status: *Clear*), or **Edit & Revalidate** records inline.
- **Report Validation Status Model**:
  - `Clear`: All validation checks passed, zero unresolved discrepancies.
  - `Reviewed with Exceptions`: Proceeded under authorized managerial exception policy.
  - `Needs Human Review`: Blocked from final approval due to unresolved issues.
- **Interactive Streamlit Web UI**:
  - Interactive Data Editor, Custom CSV File Uploader, and dedicated Persistent Memory & Report History Console.
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
│ • Deterministic Filtering (Date range, Employee, Category)             │
│ • Keyword-based Categorization                                         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    ↓ (Structured Expense Analysis)
┌────────────────────────────────────────────────────────────────────────┐
│ 🛡️ AGENT 2: VALIDATION AGENT                                           │
│ • Receipt Completeness & Amount Verification                           │
│ • Duplicate Transaction Detection                                      │
│ • Persistence of Structured Issues into SQLite Memory                  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    ↓
                 [Discrepancies Detected?]
                        /               \
                    YES                  NO
                    /                     \
┌───────────────────────────┐              \
│ 👤 HUMAN-IN-THE-LOOP      │               \
│ • Exclude flagged items   │                \
│ • Accept exceptions       │                 \
│ • Edit & Revalidate       │                  \
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

1. **Python 3.10+** (tested with 3.13)
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

## 🎯 Demonstration & Evaluation Walkthrough

### 1. Demonstrating Unit III: Persistent SQLite Memory
1. **Show Database Separation**: Point out [`data/expense_memory.db`](file:///c:/Users/Space/OneDrive/Documents/AI%20Agent%20Expense%20report/data/expense_memory.db) (business data & issues) vs [`.checkpoints/agent_state.db`](file:///c:/Users/Space/OneDrive/Documents/AI%20Agent%20Expense%20report/.checkpoints/agent_state.db) (LangGraph thread checkpoints).
2. **Demonstrate Ingestion & Deduplication**:
   - Go to tab **"🧠 Persistent SQLite Memory & History"** in the web UI.
   - Click **"📥 Ingest Master CSV to Memory"** once: `✓ Ingested 170 new records (0 duplicates skipped)`.
   - Click it a second time: `✓ Ingested 0 new records (170 duplicates skipped)` (proving SHA-256 batch deduplication).
3. **Demonstrate Historical Retrieval Without CSV Uploads**:
   - Enter: `"Generate travel expense report for last month"`.
   - Leave custom file upload empty and run agent. Notice logs: `Retrieved 170 records from persistent memory (memory_db)`.
4. **Demonstrate Compliance Issue Tracking & Resolution**:
   - When the HITL review triggers for missing receipts, select **"Accept with Managerial Exception"** and provide an approval note.
   - Re-check the memory tab: the issue is updated from `unresolved` to `accepted_exception` in SQLite.
5. **Demonstrate Stored Report Runs**:
   - In the memory tab under **"📜 Historical Report Runs"**, view the saved run ID (`REP-xxxxxxxx`), grand total, and download the verified PDF.

### 2. Demonstrating Unit IV: Multi-Agent Collaboration
1. **Three Discrete Agents**:
   - **Expense Analysis Agent**: Interprets natural language, retrieves from memory, dynamically matches employee entities, and filters records.
   - **Validation Agent**: Audits receipt completeness, non-zero amounts, and duplicate transactions; persists structured issues to SQLite.
   - **Report Generation Agent**: Enforces validation guards (refuses silent approval of unresolved issues), computes deterministic Pandas math, renders ReportLab PDF with validation status badges, and archives the run.
2. **Audit Status Badges in Final Report**:
   - Green: `VERIFIED & CLEAR` (100% compliant).
   - Amber: `REVIEWED WITH DOCUMENTED EXCEPTIONS` (Approved with recorded reviewer notes).
   - Red: `NEEDS HUMAN REVIEW` (Unresolved discrepancies).

---

## 🧪 Running the Test Suites

All tests run locally using isolated temporary fixtures without requiring external APIs or Ollama:

```bash
# 1. Run core tool tests (filtering, calculations, PDF engine, regex extraction)
python test_tools.py

# 2. Run email drafting, validation, and simulation tests
python -m unittest test_email_tools.py

# 3. Run Unit III (Persistent Memory) & Unit IV (Multi-Agent Collaboration) tests
python -m unittest test_memory_and_agents.py
```

---

## 📁 Project Structure

```
AI Agent Expense report/
├── app.py                      # Streamlit UI: Multi-agent tracking, HITL review, memory console
├── agent.py                    # LangGraph workflow connecting the 3 collaborating agents
├── state.py                    # AgentState TypedDict definition
├── tools/
│   ├── memory_tools.py         # Unit III: SQLite persistent memory, deduplication, report history
│   ├── expense_tools.py        # CSV loading, currency cleaning, date/employee filtering
│   ├── validation_tools.py     # Compliance audit, category inference, single-record revalidation
│   ├── calculation_tools.py    # Deterministic financial math & subtotals (Pandas)
│   ├── pdf_tools.py            # ReportLab PDF engine with validation status badges
│   └── email_tools.py          # Qwen 3 email draft generation & Resend API dispatch
├── data/
│   ├── expense_memory.db       # Unit III: Persistent business-data database
│   ├── expenses.csv            # Master dataset (170 entries across 5 months & 5 employees)
│   └── sample_csvs/            # Additional scenario datasets
├── .checkpoints/
│   └── agent_state.db          # LangGraph workflow state checkpointer
├── reports/                    # Generated output PDF expense reports
├── test_tools.py               # Functional test suite for core tools
├── test_email_tools.py         # Unit tests for email drafting & simulation
├── test_memory_and_agents.py   # Comprehensive tests for memory & multi-agent collaboration
├── requirements.txt            # Python dependencies
├── PROJECT_INFO.md             # Complete technical architecture & developer blueprint
└── README.md                   # Project documentation
```

---

## 🛡️ Database Separation & Resetting

- **Business Memory Database**: [`data/expense_memory.db`](file:///c:/Users/Space/OneDrive/Documents/AI%20Agent%20Expense%20report/data/expense_memory.db)
  - Contains persistent tables: `expenses`, `import_batches`, `validation_issues`, `report_runs`, and `audit_events`.
- **Workflow Checkpoint Database**: [`.checkpoints/agent_state.db`](file:///c:/Users/Space/OneDrive/Documents/AI%20Agent%20Expense%20report/.checkpoints/agent_state.db)
  - Contains LangGraph thread checkpoints used solely to pause and resume agent workflows during HITL reviews.

**Safe Database Reset**:
To reset the development/test memory database without affecting source CSV data:
```bash
del data\expense_memory.db
```
The database will automatically reinitialize its schema on the next run.
