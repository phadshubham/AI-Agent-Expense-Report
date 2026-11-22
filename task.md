# 📋 Project Task & Design Context

## Design Context

### Users
- **Primary Persona**: Finance Managers, Corporate Controllers, and Compliance Auditors.
- **Working Environment**: Fast-paced corporate finance departments and auditing environments where accuracy, regulatory compliance, and speed are essential.
- **Jobs to be Done**:
  - Autonomously generate verifiable, period-accurate expense reports from free-form natural language queries.
  - Audit transactions for compliance discrepancies (missing receipts, invalid amounts, duplicate charges, unverified line items).
  - Review and authorize managerial exceptions with explicit audit notes without risking silent approvals.
  - Review persistent historical report runs, query past transactions, and inspect cryptographic batch ingestions across sessions.
  - Dispatch publication-grade executive PDF reports and AI-drafted email summaries to stakeholders.
- **Desired Emotional Experience**: Absolute confidence, clarity, rigorous control, and seamless transparency. Every calculation and approval decision must feel deliberate, traceable, and legally defensible.

### Brand Personality
- **Three-Word Personality**: **Authoritative, Crisp, Trustworthy**.
- **Voice & Tone**: Objective, executive, professional, and audit-focused. Clear and decisive messaging without decorative fluff or ambiguous status indicators.
- **Design References**: Modern FinTech and Enterprise benchmarks including **Stripe**, **Ramp**, and **Mercury**. Clean visual hierarchy, crisp tabular figures, subtle elevation, and purposeful card grouping.
- **Anti-References**: 
  - Cluttered legacy ERP systems (SAP/Oracle tables with tiny unreadable text and no visual pacing).
  - Generic "AI Slop" (cyan/purple glowing dark mode gradients, excessive glassmorphism, meaningless animated sparklines, decorative gradient text).
  - Flashy neon dashboards with ungrounded metrics.

### Aesthetic Direction
- **Visual Style**: Modern FinTech / Enterprise — high utility, disciplined spacing, and balanced executive density.
- **Theme**: Crisp Light Theme with brand-tinted slate neutral surfaces and deep navy/indigo anchors.
- **Color Palette & Tokens**:
  - **Brand Primary**: Deep Navy / Indigo (`#1a237e`, `#0f172a`) — authoritative headers, primary buttons, brand accents.
  - **Surface & Backgrounds**: Clean Crisp Slate (`#f8fafc` app canvas, `#ffffff` card surface, `#f1f5f9` muted container).
  - **Border & Dividers**: Subtle Stone / Slate (`#e2e8f0`, `#cbd5e1`).
  - **Text Hierarchy**: `#0f172a` (Primary headings & values), `#334155` (Body text), `#64748b` (Secondary labels & captions).
  - **Semantic Indicators**:
    - *Success / Verified*: Emerald (`#059669`, background `#ecfdf5`, border `#a7f3d0`).
    - *Warning / Exceptions / Review*: Amber (`#d97706`, background `#fffbeb`, border `#fde68a`).
    - *Error / Discrepancy*: Crimson (`#dc2626`, background `#fef2f2`, border `#fecaca`).
    - *Info / Active Agent*: Indigo-Blue (`#2563eb`, background `#eff6ff`, border `#bfdbfe`).
    - *Neutral / Completed*: Slate (`#64748b`, background `#f8fafc`, border `#e2e8f0`).
- **Typography & Data Presentation**:
  - Sans-serif system / modern font stack (`Plus Jakarta Sans`, `-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `sans-serif`).
  - Strict `font-variant-numeric: tabular-nums` for all financial figures, currencies, dates, and metric cards.
  - Multi-tier typography scale: large unambiguous financial totals, readable structured tables, clear status chips.

### Design Principles
1. **Audit Truthfulness & Zero Silent Approvals**: Financial data and compliance statuses must never be obfuscated or glossed over. Every unresolved issue must be visually apparent and require explicit human intervention.
2. **Deterministic Clarity & Tabular Scannability**: Financial figures must be scannable in seconds. Currency symbols, decimal alignments, and line items must use tabular numerals with high visual contrast.
3. **Truthful Multi-Agent Transparency**: Every phase of multi-agent execution (Expense Analysis, Validation, Report Generation) must display honest, real-time status with distinct operational badges (Running, Completed, Interrupted, Failed).
4. **Purposeful Visual Hierarchy & Intentional Actions**: High-priority workflows (Execute Agent, Authorize Exception, Exclude, Download PDF, Send Email) must have unmistakable visual prominence, while secondary controls remain unobtrusive.
5. **Persistent Context & Cohesive Continuity**: Navigation across Dashboard, Prompt History, Persistent SQLite Memory, and Compliance Audit must maintain unified styling, status badge conventions, and component grammar.

---

## Architecture & Master Task Repair Status

### Milestone 1: Database Architecture & Safe Schema Migration (user_version = 2) ✅
- **Root Cause Fixed**: Legacy `expenses` table had `amount REAL NOT NULL`, which threw `sqlite3.IntegrityError: NOT NULL constraint failed: expenses.amount` whenever records with null/missing amounts were ingested.
- **Schema Upgrade**: Migrated to `expenses_v2` with `amount REAL NULL`, `location TEXT NULL`, `expense_date TEXT NULL`, `is_excluded INTEGER NOT NULL DEFAULT 0`, `dataset_id`, and `dataset_version`.
- **Backward-Compatibility**: Created views `expenses`, `validation_issues`, and `report_runs` with `INSTEAD OF` triggers (`trg_expenses_insert`, `trg_expenses_update`, `trg_expenses_delete`, etc.).
- **Foreign Key Resilience**: Implemented `_ensure_dataset_registered` across `save_expenses`, `save_validation_issues`, `save_report_run`, and `save_audit_event` to guarantee foreign keys always resolve cleanly.
- **Automated Tests**: 16/16 passed in `tests/test_milestone1_db.py`.

### Milestone 2: Canonical Filter Pipeline & State Leakage Elimination ✅
- **Root Cause Fixed**: Agent 1 was reusing prior prompt state (`state.get("employee_name")`) when an all-employee query was submitted.
- **Zero State Leakage**: Derived target employee strictly from `user_request` and dynamic dataset employees via `extract_canonical_filters`.
- **Location Schema Aliasing**: Flexible support for `location`, `city`, and `destination` headers via `normalize_expense_columns` without data fabrication.
- **Typo Tolerance & Clean Boundaries**: Added whitespace normalization and regex boundaries for employee names, months, and categories.
- **Automated Tests**: 42/42 passed in `tests/test_milestone2_filters.py`.

### Milestone 3: Compliance & Validation Workspace (`apply_reviewer_decision`) ✅
- **Reviewer Actions**:
  - `correct`: In-place 8-field update to `expenses_v2`, revalidates record via `revalidate_single_expense`, resolves issue in `validation_issues_v2`, and logs `reviewer_correction` audit event.
  - `exclude` / `exclude_single`: Marks `is_excluded = 1`, removes record from financial calculations, resolves issue as `excluded`, and logs `reviewer_exclusion` audit event.
  - `accept_exception`: Authorizes managerial override, updates status to `accepted_exception`, and logs `reviewer_exception_accepted` audit event.
- **Persistent HITL Memory & Automatic Workflow Continuity**:
  - Direct auditor resolutions in Tab 4 (`❌ Exclude from Counting & Reports` or `✅ Authorize Managerial Exception`) are permanently recorded in SQLite memory (`expenses_v2` and `validation_issues_v2`).
  - When the multi-agent workflow runs, the Validation Agent inspects persistent memory:
    - Pre-authorized exceptions are recognized and marked `"Reviewed with Exceptions"` with audit trail documentation.
    - Pre-excluded transactions (`is_excluded = 1`) are completely omitted from counting and reports.
    - When all flagged transactions have been audited/resolved, **the workflow DOES NOT interrupt for Human Review**; it remembers the user's prior decisions and **just continues** straight to Report Generation.
    - Zero silent approvals: Un-audited/unresolved issues continue to reliably trigger Human-in-the-Loop review.
- **Automated Tests**: 8/8 passed in `tests/test_milestone3_compliance.py`.

### Milestone 4: Streamlit UI Modernization (`app.py`) ✅
- **Active Dataset Header**: Prominent banner showing dataset name, version, transaction count, file hash, and active chip.
- **Interactive Data Editor**: Positioned on Tab 1 with `st.data_editor(num_rows="dynamic")`. Supports inline edits, adding/deleting rows, and saving as a new version.
- **Null Resilience in HITL Review**:
  - Records with null amounts or missing dates are audited and presented in the Human-in-the-Loop review console.
  - Users are offered the choice to **Input Value** (with date, receipt status, and location) or **Exclude from Counting**.
- **Data Isolation**: History on Tab 2 and issues on Tab 4 strictly scoped to active dataset.
- **Automated Tests**: 252/252 passed in `tests/test_e2e_tier1_features.py` through `tier4`.

### Milestone 5: Adversarial Hardening & Verification ✅
- **Adversarial Resilience**: SQL injection resilience, malformed/all-null rows, Unicode/emoji preservation, and prompt whitespace fuzzing verified.
- **Automated Tests**: 6/6 passed in `tests/test_e2e_tier5_adversarial.py`.
- **Full Test Suite Status**: **324 / 324 PASSED in 17.14s**.
