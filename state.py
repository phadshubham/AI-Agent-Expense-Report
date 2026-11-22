"""
State definition for the Expense Report Agent.

Defines the AgentState TypedDict used by LangGraph to maintain
workflow state throughout the expense report generation pipeline,
supporting multi-agent collaboration (Expense Analysis Agent,
Validation Agent, Report Generation Agent) and persistent SQLite memory.
"""

from typing import TypedDict, Annotated, Optional, List, Dict, Any
from langgraph.graph.message import add_messages


class ParsedFilters(TypedDict, total=False):
    """
    Canonical filter criteria extracted from natural-language prompts.
    Shared consistently across parser, agent state, DB queries, and UI.
    """
    start_date: Optional[str]         # YYYY-MM-DD (inclusive) or None
    end_date: Optional[str]           # YYYY-MM-DD (inclusive) or None
    time_period_label: str            # e.g., "last month", "August 2026", "all"
    expense_type: str                 # "all" | "travel"
    employee: Optional[str]           # Specific employee name or None
    category: Optional[str]           # Expense category (e.g. "Flight", "Meals") or None
    merchant: Optional[str]           # Specific merchant or None
    location: Optional[str]           # Destination/city or None
    raw_prompt: str                   # Original user request string


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
    dataset_id: Optional[str]   # Active dataset identifier
    dataset_version: Optional[int] # Active dataset version number
    
    # --- User Request Parsing & Canonical Filters ---
    user_request: str           # Original natural-language request
    start_date: str             # Computed start date (YYYY-MM-DD)
    end_date: str               # Computed end date (YYYY-MM-DD)
    expense_type: str           # e.g., "travel", "all"
    employee_name: str          # Employee name (or 'Company Team' for multi-employee)
    target_employee: str        # Explicit employee filter from prompt (if any)
    parsed_filters: Optional[ParsedFilters] # Canonical filter object
    filter_match_count: Optional[int]       # Number of records matching parsed_filters
    zero_match_explanation: Optional[str]   # Diagnostic explanation when 0 records match
    location_supported: Optional[bool]      # False if dataset lacks location/city columns
    
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
