# Role Dossier: Shubham Phad (ADT23SOCB1106)
## Lead Agentic AI & State Machine Orchestration Engineer

---

### 1. Executive Summary & Core Identity
As the **Lead Agentic AI & State Machine Orchestration Engineer**, you are the brain of the system. You designed and implemented the **LangGraph multi-agent orchestration architecture**, the **state machine transitions**, the **three collaborating agents**, and the **natural-language understanding (NLU) intent pipeline**. 

If the teacher asks: *"How does the AI actually work in this project?"* — **You are the one who answers.**

---

### 2. Modules & Core Architecture Owned

#### A. LangGraph Multi-Agent Architecture (`agent.py`, `state.py`)
* Built an autonomous, state-driven workflow using **LangGraph 0.2+ `StateGraph`**.
* Implemented a unified graph state model (`ExpenseAgentState`) that flows through three discrete nodes:
  1. `analyze_expenses` (Agent 1: Expense Analysis Agent)
  2. `validate_expenses` (Agent 2: Compliance & Validation Agent)
  3. `generate_report` (Agent 3: Report Generation Agent)
* Designed conditional decision edges (`check_zero_records` and `check_validation_status`) that govern execution branching.
* Bound the state machine to an isolated SQLite checkpointer (`.checkpoints/agent_state.db`) using `SqliteSaver` to support non-blocking Human-in-the-Loop execution.

#### B. Agent 1: Expense Analysis Agent (`tools/expense_tools.py`, `agent.py`)
* **Natural-Language Intent Extraction**: Dual-engine architecture combining local **Ollama Qwen 3** with a fast deterministic **Regex Fallback Engine**.
* **Dynamic Entity Resolution**: Fuzzy-matches user-typed employee names (e.g., *"ravi"* or *"Priya"*) against the active dataset employee registry using **RapidFuzz** with an 80% threshold.
* **Temporal Window Normalization**: Converts phrases like *"last month"*, *"travel in August"*, or *"Q2"* into strict calendar bounding intervals `[start_date, end_date]`.
* **Zero-Record Boundary Diagnostics**: If an intent query yields 0 matching records, Agent 1 prevents silent failure by calculating dataset temporal coverage (e.g., *"Dataset dates range from 2026-06-10 to 2026-08-12; no records found for 2026-10-01 to 2026-10-31"*).

#### C. Agent 2: Compliance & Validation Agent (`tools/validation_tools.py`, `agent.py`)
* Audits candidate transactions against corporate financial rules:
  * **Single Meal Cap**: Flagged if $> ₹1,500$
  * **Daily Aggregate Limit**: Flagged if cumulative spend in a single day $> ₹5,000$
  * **Intercity Travel Cap**: Flagged if $> ₹25,000$
  * **Mandatory Receipts**: Flagged if receipt status is `Missing` or absent.
  * **Non-Zero / Non-Null Integrity**: Flagged if amount $\le 0$ or null.
* Cross-references persistent memory (`validation_issues_v2`) to check if a human auditor previously authorized an exception for that record ID.
* If unresolved issues remain, raises a **`GraphInterrupt`** to demand managerial review.

#### D. Agent 3: Report Generation Agent (`tools/calculation_tools.py`, `agent.py`)
* Enforces the **Mathematical Integrity Guard**: strictly forbids the LLM from doing arithmetic.
* Executes vectorized Python/Pandas aggregation tools to compute total spend, category breakdowns, employee subtotals, and average transaction size.
* Compiles clean Markdown report drafts and triggers the PDF compilation engine.

---

### 3. Critical Code You Authored & Must Walk Through

#### A. Unified State Schema (`state.py`)
```python
from typing import TypedDict, List, Dict, Any, Optional

class ExpenseAgentState(TypedDict):
    """
    Central immutable state passed across all LangGraph nodes.
    """
    user_prompt: str
    dataset_id: str                      # Scoped dataset isolation
    expenses: List[Dict[str, Any]]        # Active candidate records
    parsed_criteria: Dict[str, Any]       # Extracted NLU intent
    validation_issues: List[Dict[str, Any]] # Audit discrepancies
    validation_status: str                # 'compliant', 'violations_found', 'exception_approved'
    needs_human_review: bool              # HITL escalation flag
    reviewer_action: Optional[str]        # 'accept_exception', 'exclude', 'correct'
    calculation_summary: Dict[str, Any]   # Deterministic arithmetic totals
    report_content: str                   # Synthesized report markdown
    pdf_path: Optional[str]               # Path to generated vector PDF
    email_draft: Optional[Dict[str, Any]] # AI executive email draft
    audit_trail: List[str]                # Chronological agent telemetry log
```

#### B. LangGraph Workflow Graph Definition (`agent.py`)
```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

def create_expense_graph(checkpointer: SqliteSaver):
    builder = StateGraph(ExpenseAgentState)

    # 1. Register specialized agent nodes
    builder.add_node("analyze_expenses", analyze_expenses_node)
    builder.add_node("validate_expenses", validate_expenses_node)
    builder.add_node("generate_report", generate_report_node)

    # 2. Define starting entrypoint
    builder.set_entry_point("analyze_expenses")

    # 3. Conditional routing: Zero records check
    builder.add_conditional_edges(
        "analyze_expenses",
        check_zero_records,
        {
            "abort": END,                     # Graceful exit with diagnostic notice
            "proceed": "validate_expenses"   # Hand off to compliance agent
        }
    )

    # 4. Conditional routing: Policy violation / HITL check
    builder.add_conditional_edges(
        "validate_expenses",
        check_validation_status,
        {
            "require_human": END,            # GraphInterrupt pause awaiting resume
            "clear": "generate_report"       # Proceed directly to report generation
        }
    )

    # 5. Final completion edge
    builder.add_edge("generate_report", END)

    return builder.compile(checkpointer=checkpointer)
```

#### C. Mathematical Integrity Guard (`tools/calculation_tools.py`)
```python
import pandas as pd

def calculate_deterministic_summary(records: list) -> dict:
    """
    Zero LLM arithmetic. 100% vectorized Pandas verification.
    """
    if not records:
        return {"total_amount": 0.0, "count": 0, "categories": {}}

    df = pd.DataFrame(records)
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)

    total_spend = round(float(df["amount"].sum()), 2)
    tx_count = int(len(df))
    cat_breakdown = df.groupby("category")["amount"].sum().round(2).to_dict()
    emp_breakdown = df.groupby("employee")["amount"].sum().round(2).to_dict()

    return {
        "total_amount": total_spend,
        "record_count": tx_count,
        "by_category": cat_breakdown,
        "by_employee": emp_breakdown,
        "average_transaction": round(total_spend / tx_count, 2) if tx_count > 0 else 0.0
    }
```

---

### 4. Likely Teacher / Viva Questions & Model Answers

* **Q1: "Why did you use LangGraph instead of just asking GPT-4 or Claude to do everything in one prompt?"**
  * **Your Answer**: *"Single-shot prompts suffer from arithmetic hallucination (error rates exceeding 15% on tabular columns) and context exhaustion. By using LangGraph, we decouple linguistic intent parsing (Agent 1) from corporate compliance auditing (Agent 2) and deterministic mathematical aggregation (Agent 3). More importantly, LangGraph gives us stateful checkpointing, so the workflow can safely halt when a policy violation occurs and wait for human managerial approval without losing execution state."*

* **Q2: "What happens if local Ollama Qwen 3 is offline or slow on the machine?"**
  * **Your Answer**: *"I built a deterministic Regex Fallback Engine. If Ollama times out or is unreachable, the system automatically catches the exception, switches to regex-based entity and temporal parsing, and successfully extracts target employees and date ranges. The user never sees a crash."*

* **Q3: "How does dynamic employee matching work if the user types 'ravi' instead of 'Ravi Kumar'?"**
  * **Your Answer**: *"In `tools/expense_tools.py`, I query the active dataset's distinct employee names and use `RapidFuzz.process.extractOne()` with token-sort scoring. If the score is $\ge 80\%$, it binds the query to the exact canonical name in the database. If no match meets the threshold, it alerts the user rather than guessing."*

* **Q4: "Who does the math in your system?"**
  * **Your Answer**: *"Only deterministic Python and Pandas. The LLM is strictly prohibited from summing numbers. Agent 3 invokes our Pandas calculation tool, computes exact sums, and passes the numbers as immutable constants into the report."*
