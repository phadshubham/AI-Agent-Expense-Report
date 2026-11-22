# Role Dossier: Kaustubh Manjarekar (ADT23SOCB0510)
## Compliance Governance, Document Vector Systems & QA Lead

---

### 1. Executive Summary & Core Identity
As the **Compliance Governance, Document Vector Systems & QA Lead**, you own the **Human-in-the-Loop (HITL) review system**, the **Auditor Direct Resolution console**, the **Publication-Grade ReportLab Vector PDF Engine** (`tools/pdf_tools.py`), and the **324-test Automated QA Verification Suite** (`tests/`).

If the teacher asks: *"How does the system enforce Human-in-the-Loop approval?", "How are official audit-badged PDFs compiled?", "What happens if a policy violation occurs?"* or *"How do you test and verify the entire platform?"* — **You are the one who answers.**

---

### 2. Modules & Core Architecture Owned

#### A. Human-in-the-Loop (HITL) Review System (`agent.py`, `app.py`)
* Implemented the **`GraphInterrupt`** interception in LangGraph. When the Validation Agent detects missing receipts or policy limit violations (> ₹1,500 meal, > ₹5,000 day, > ₹25,000 travel), the workflow halts automatically.
* The execution graph is serialized into `.checkpoints/agent_state.db` using `SqliteSaver`.
* Built the **Resume Mechanism**: When a human compliance manager reviews the issue, the system resumes execution via **`Command(resume={"action": action, ...})`**, updating the graph state without restarting from scratch.

#### B. Auditor Direct Resolution Console (`app.py`, `tools/memory_tools.py`)
* Created the interactive **Compliance & Audit Issue Management** interface.
* Enabled compliance auditors to document authorized managerial actions:
  * `accept_exception`: Approves an out-of-policy transaction with documented managerial justification (e.g., *"Client emergency dinner approved by director"*).
  * `exclude`: Completely removes the non-compliant transaction from subsequent financial aggregation and reports.
  * `correct`: Fixes the record values directly in SQLite persistent memory.
* Cryptographically logs every resolution with reviewer ID, timestamp, and justification into `audit_events` for non-repudiation.

#### C. Publication-Grade Vector PDF Generation Engine (`tools/pdf_tools.py`)
* Developed the dynamic vector PDF generation engine using **ReportLab** (`SimpleDocTemplate`, `Table`, `Paragraph`, `Image`, `PageBreak`).
* **Official Compliance Audit Badges**:
  * Emits an emerald **`100% COMPLIANT`** badge if all transactions strictly adhere to corporate policy.
  * Emits an amber **`APPROVED WITH EXCEPTIONS`** badge if managerial exceptions were authorized, rendering an itemized exception table directly on the cover.
* Built dynamic table pagination that calculates column widths, prevents text truncation, and wraps long merchant descriptions cleanly.

#### D. Comprehensive 324-Test Automated QA Verification Suite (`tests/`)
* Architected and implemented the entire automated test suite consisting of **324 tests across 4 rigorous tiers**:
  * **Tier 1 (Storage & Isolation - 98 tests)**: Verifies SQLite schema migrations, SHA-256 dataset isolation, content-hash pooling, and foreign key integrity.
  * **Tier 2 (Vector PDF & Mathematical Guard - 74 tests)**: Verifies ReportLab layout, exact sum/mean reconciliation, badge color thresholds, and table pagination.
  * **Tier 3 (LangGraph Orchestration & HITL - 82 tests)**: Verifies `StateGraph` transitions, `SqliteSaver` checkpoints, `GraphInterrupt` triggers, and `Command(resume)` feedback loops.
  * **Tier 4 (Edge Cases & Resilience - 70 tests)**: Verifies zero-record date bounds, dirty string amounts, null receipts, and duplicate batch prevention.
* **100% Test Pass Rate**: All 324 tests pass in under 11 seconds (`324 passed in 10.68s`).

---

### 3. Critical Code You Authored & Must Walk Through

#### A. Human-in-the-Loop Interrupt & Resume Handler (`agent.py`, `app.py`)
```python
from langgraph.types import Command, interrupt

def validate_expenses_node(state: ExpenseAgentState):
    """
    Agent 2 node: If unresolved violations exist, trigger GraphInterrupt.
    """
    issues = detect_compliance_issues(state["expenses"], state["dataset_id"])
    
    # Check if any unresolved issues remain
    unresolved = [iss for iss in issues if iss.get("status") == "unresolved"]
    
    if unresolved:
        # Halt execution graph and yield control to human reviewer
        user_decision = interrupt({
            "message": f"Detected {len(unresolved)} policy violation(s). Managerial review required.",
            "unresolved_issues": unresolved
        })
        
        # When resumed via Command(resume=...), execution continues here
        action = user_decision.get("action")
        return {
            "validation_status": "exception_approved" if action == "accept_exception" else "violations_addressed",
            "reviewer_action": action
        }
        
    return {"validation_status": "compliant", "validation_issues": []}
```

#### B. Publication-Grade Vector PDF Generation with Badges (`tools/pdf_tools.py`)
```python
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image
from reportlab.lib import colors

def generate_vector_expense_pdf(report_data: dict, output_path: str):
    doc = SimpleDocTemplate(output_path, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=40, bottomMargin=40)
    story = []
    
    # Compliance Badge Logic
    is_compliant = report_data.get("is_compliant", True)
    badge_bg = colors.HexColor("#ecfdf5") if is_compliant else colors.HexColor("#fffbeb")
    badge_border = colors.HexColor("#059669") if is_compliant else colors.HexColor("#d97706")
    badge_text = "100% COMPLIANT (CORPORATE AUDIT PASSED)" if is_compliant else "APPROVED WITH MANAGERIAL EXCEPTIONS"
    
    badge_table = Table([[Paragraph(f"<b>OFFICIAL AUDIT STATUS:</b> {badge_text}", badge_style)]], colWidths=[523])
    badge_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), badge_bg),
        ('BOX', (0,0), (-1,-1), 1.5, badge_border),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(badge_table)
    story.append(Spacer(1, 12))
    
    # Itemized Transaction Table with automatic column wrapping
    ...
    doc.build(story)
```

---

### 4. Likely Teacher / Viva Questions & Model Answers

* **Q1: "How does the system stop for a human when an out-of-policy expense occurs, and how does it resume?"**
  * **Your Answer**: *"In LangGraph, we use the `interrupt()` primitive inside `validate_expenses_node`. When unresolved violations are detected, `interrupt()` halts execution and LangGraph serializes the entire state machine into `.checkpoints/agent_state.db`. In the UI, the auditor selects `accept_exception` or `exclude`. When submitted, we invoke `agent.invoke(Command(resume=decision), config=thread_config)`. The graph resumes from the exact checkpoint without re-running Agent 1."*

* **Q2: "Why did you use ReportLab instead of just converting an HTML page or screenshot into a PDF?"**
  * **Your Answer**: *"HTML-to-PDF rendering tools frequently produce blurry text, break tables awkwardly across pages, and lack precise vector geometry. ReportLab compiles true resolution-independent vector graphics, draws crisp table borders, enables dynamic pagination, and computes mathematical layout bounds with 100% deterministic visual fidelity."*

* **Q3: "How do your 324 automated tests verify that the system is bug-free?"**
  * **Your Answer**: *"We designed a 4-tier test pyramid in `pytest`: Tier 1 tests SQLite schema and SHA-256 dataset isolation; Tier 2 validates ReportLab math and badge generation; Tier 3 tests LangGraph state transitions and HITL `Command(resume)` execution; Tier 4 tests edge cases like dirty CSV amounts and duplicate uploads. All 324 tests execute in 10.68 seconds with a 100% pass rate."*
