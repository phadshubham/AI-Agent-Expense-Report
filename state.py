"""
State definition for the Expense Report Agent.

Defines the AgentState TypedDict used by LangGraph to maintain
workflow state throughout the expense report generation pipeline,
supporting multi-agent collaboration (Expense Analysis Agent,
Validation Agent, Report Generation Agent) and persistent SQLite memory.
"""

from typing import TypedDict, Annotated, Optional, List, Dict, Any
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """
    Complete state for the Multi-Agent Expense Report workflow.
    
    LangGraph maintains this state across all collaborating agents.
    The 'messages' field uses the add_messages reducer to accumulate
    conversation history. All other fields are updated deterministically.
    """
    # --- Conversation ---
    messages: Annotated[list, add_messages]
    
    # --- Identification & Memory Tracking ---
    report_run_id: str          # Unique ID for this report run (e.g. REP-xxxxxxxx)
    data_source: str            # 'memory_db' | 'csv_file' | 'interactive_editor'
    
    # --- User Request Parsing ---
    user_request: str           # Original natural-language request
    start_date: str             # Computed start date (YYYY-MM-DD)
    end_date: str               # Computed end date (YYYY-MM-DD)
    expense_type: str           # e.g., "travel", "all"
    employee_name: str          # Employee name (or 'Company Team' for multi-employee)
    target_employee: str        # Explicit employee filter from prompt (if any)
    
    # --- Multi-Agent Collaboration Data ---
    # Agent 1: Expense Analysis Agent output
    expense_analysis: dict      # Structured analysis output from Expense Analysis Agent
    
    # Agent 2: Validation Agent output
    validation_findings: list   # Structured validation issues from Validation Agent
    unresolved_count: int       # Number of unresolved validation issues
    validation_status: str      # 'Clear' | 'Needs Human Review' | 'Reviewed with Exceptions'
    
    # Human Review & Resolutions (HITL)
    human_decisions: list       # Audit trail of decisions made during review (exclude, override, edit)
    human_response: str         # Raw user response to interrupt ("include", "exclude", "correct")
    
    # Agent 3: Report Generation Agent output
    report_payload: dict        # Final payload assembled for PDF generation and DB persistence
    
    # --- Data Pipeline (Backward Compatible) ---
    expenses: list              # Raw expenses (from CSV or Memory DB)
    filtered_expenses: list     # After date/type/employee filtering
    categorized_expenses: list  # After categorization (with excluded items removed if decided)
    missing_data: list          # Validation issues (compatible with existing UI/PDF tools)
    totals: dict                # Calculated totals by category and employee
    
    # --- Output ---
    pdf_path: str               # Path to generated PDF
    
    # --- Email Dispatch ---
    recipient_email: str        # Destination email address
    email_subject: str          # Qwen 3 generated or edited email subject
    email_body: str             # Qwen 3 generated or edited email body
    email_status: str           # Status message of email dispatch
    
    # --- Execution & Agent Logging ---
    agent_logs: list            # Structured logs per agent: [{"agent": str, "message": str, "timestamp": str}]
    workflow_status: list       # Progress messages for UI display
    awaiting_input: str         # "" | "missing_data"
    error: str                  # Error message if something fails
