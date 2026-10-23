"""
Persistent SQLite Memory Tools for the AI Expense Report Agent.

Provides long-term storage and retrieval of:
- Expense records (with deduplication on import)
- Validation issues and audit resolution history
- Historical report runs and validation statuses
- Audit events for compliance tracking

Database location: data/expense_memory.db
(Separated cleanly from LangGraph's workflow checkpoint database .checkpoints/agent_state.db)
"""

import os
import sqlite3
import hashlib
import json
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple


DEFAULT_MEMORY_DB_PATH = os.path.join("data", "expense_memory.db")


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Return the absolute or resolved database path."""
    if custom_path:
        return custom_path
    env_path = os.getenv("EXPENSE_MEMORY_DB_PATH")
    if env_path:
        return env_path
    return DEFAULT_MEMORY_DB_PATH


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Open and return a thread-safe SQLite connection with foreign keys enabled
    and row factory set to sqlite3.Row for dictionary-like access.
    """
    path = get_db_path(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_memory_db(db_path: Optional[str] = None) -> str:
    """
    Initialize SQLite schema for persistent expense memory.
    Safe to call repeatedly (uses CREATE TABLE IF NOT EXISTS).
    
    Returns:
        The database path initialized.
    """
    path = get_db_path(db_path)
    conn = get_connection(path)
    cursor = conn.cursor()

    try:
        # 1. Expense Records Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_id TEXT UNIQUE NOT NULL,
                expense_date TEXT NOT NULL,
                employee TEXT NOT NULL,
                description TEXT NOT NULL,
                merchant TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                receipt_status TEXT NOT NULL,
                receipt_path TEXT,
                source_file TEXT NOT NULL,
                import_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # Indexes for fast lookup
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenses_employee ON expenses(employee);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenses_import_hash ON expenses(import_hash);")

        # 2. Import Batches Table (to track imported files and avoid repeated full imports)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS import_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT UNIQUE NOT NULL,
                source_name TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                record_count INTEGER NOT NULL,
                imported_at TEXT NOT NULL
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_import_batches_hash ON import_batches(file_hash);")

        # 3. Validation Issues Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS validation_issues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id TEXT UNIQUE NOT NULL,
                expense_record_id TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                field_name TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'unresolved',
                detected_at TEXT NOT NULL,
                resolved_at TEXT,
                reviewer_decision TEXT,
                reviewer_notes TEXT,
                FOREIGN KEY (expense_record_id) REFERENCES expenses(record_id) ON DELETE CASCADE
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_val_issues_exp ON validation_issues(expense_record_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_val_issues_status ON validation_issues(status);")

        # 4. Report Runs Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS report_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT UNIQUE NOT NULL,
                user_request TEXT NOT NULL,
                filters_json TEXT NOT NULL,
                transaction_ids_json TEXT NOT NULL,
                transaction_count INTEGER NOT NULL,
                grand_total REAL NOT NULL,
                validation_status TEXT NOT NULL,
                report_file_path TEXT NOT NULL,
                human_review_status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_report_runs_created ON report_runs(created_at);")

        # 5. Audit Events Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);")

        conn.commit()
    finally:
        conn.close()

    return path


def _generate_record_id(record: Dict[str, Any], source: str, row_idx: int) -> str:
    """Generate a deterministic or stable record identifier."""
    # Deterministic fingerprint using key business values plus source and row index
    val_str = f"{source}:{row_idx}:{record.get('employee', '')}:{record.get('date', '')}:{record.get('merchant', '')}:{record.get('amount', 0)}"
    h = hashlib.sha256(val_str.encode("utf-8")).hexdigest()[:12]
    return f"EXP-{h}"


def _compute_import_hash(source_name: str, expenses: List[Dict[str, Any]]) -> str:
    """Compute a cryptographic hash of the entire dataset import."""
    serialized = json.dumps(
        [
            {
                "e": str(x.get("employee", "")).strip(),
                "d": str(x.get("date", "")).strip(),
                "m": str(x.get("merchant", "")).strip(),
                "a": float(x.get("amount", 0) or 0),
                "c": str(x.get("category", "")).strip(),
            }
            for x in expenses
        ],
        sort_keys=True,
    )
    return hashlib.sha256(f"{source_name}:{serialized}".encode("utf-8")).hexdigest()


def save_expenses(
    expenses: List[Dict[str, Any]],
    source_name: str = "expenses.csv",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Persistently store expense records in SQLite memory with import deduplication.
    
    If the exact same batch has already been imported, it returns existing records
    without duplicating database rows. If individual new records are present,
    they are safely inserted.
    
    Returns:
        dict: {
            "batch_id": str,
            "total_processed": int,
            "inserted": int,
            "skipped_duplicates": int,
            "records": List[dict] (records enriched with stable record_id)
        }
    """
    if not expenses:
        return {
            "batch_id": "",
            "total_processed": 0,
            "inserted": 0,
            "skipped_duplicates": 0,
            "records": [],
        }

    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    file_hash = _compute_import_hash(source_name, expenses)
    now_str = datetime.now().isoformat()
    inserted_count = 0
    skipped_count = 0
    enriched_records = []

    try:
        # Check if identical batch was already imported
        cursor.execute("SELECT batch_id FROM import_batches WHERE file_hash = ?", (file_hash,))
        existing_batch = cursor.fetchone()
        batch_id = existing_batch["batch_id"] if existing_batch else str(uuid.uuid4())

        for idx, raw_exp in enumerate(expenses):
            exp = dict(raw_exp)
            rec_id = exp.get("record_id") or _generate_record_id(exp, source_name, idx)
            exp["record_id"] = rec_id

            # Parse / format date
            exp_date = str(exp.get("date", "")).strip()
            if "T" in exp_date:
                exp_date = exp_date.split("T")[0]

            # Format amount
            try:
                amt = float(exp.get("amount", 0) or 0)
            except (ValueError, TypeError):
                amt = 0.0

            emp_name = str(exp.get("employee", "")).strip() or "Unknown"
            desc = str(exp.get("description", "")).strip()
            merchant = str(exp.get("merchant", "")).strip()
            category = str(exp.get("category", "")).strip() or "Other"
            receipt_status = str(exp.get("receipt_status", "Verified")).strip()
            receipt_path = exp.get("receipt_path", "")

            # Check if this record_id already exists in DB
            cursor.execute("SELECT id FROM expenses WHERE record_id = ?", (rec_id,))
            exists = cursor.fetchone()

            if exists:
                skipped_count += 1
            else:
                cursor.execute(
                    """
                    INSERT INTO expenses (
                        record_id, expense_date, employee, description, merchant,
                        category, amount, receipt_status, receipt_path,
                        source_file, import_hash, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec_id,
                        exp_date,
                        emp_name,
                        desc,
                        merchant,
                        category,
                        amt,
                        receipt_status,
                        receipt_path,
                        source_name,
                        file_hash,
                        now_str,
                        now_str,
                    ),
                )
                inserted_count += 1

            enriched_records.append({
                "record_id": rec_id,
                "date": exp_date,
                "employee": emp_name,
                "description": desc,
                "merchant": merchant,
                "category": category,
                "amount": amt,
                "receipt_status": receipt_status,
                "receipt_path": receipt_path,
                "source_file": source_name,
            })

        # Record import batch if new
        if not existing_batch:
            cursor.execute(
                """
                INSERT INTO import_batches (batch_id, source_name, file_hash, record_count, imported_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (batch_id, source_name, file_hash, len(expenses), now_str),
            )

        conn.commit()
    finally:
        conn.close()

    return {
        "batch_id": batch_id,
        "total_processed": len(expenses),
        "inserted": inserted_count,
        "skipped_duplicates": skipped_count,
        "records": enriched_records,
    }


def retrieve_expenses_from_db(
    employee: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    expense_type: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve stored expense records with parameterized filtering.
    
    Args:
        employee: Optional case-insensitive employee name filter.
        start_date: YYYY-MM-DD (inclusive)
        end_date: YYYY-MM-DD (inclusive)
        category: Category name (e.g. "Flight", "Meals")
        expense_type: If "travel", filters to Flight, Transport, Accommodation, Meals.
        db_path: Optional custom db path.
        
    Returns:
        List of matching expense dictionaries.
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    travel_categories = ["flight", "transport", "accommodation", "meals"]

    query = "SELECT * FROM expenses WHERE 1=1"
    params: List[Any] = []

    if start_date:
        query += " AND expense_date >= ?"
        params.append(start_date)

    if end_date:
        query += " AND expense_date <= ?"
        params.append(end_date)

    if employee and employee.strip():
        emp_clean = employee.strip().lower()
        query += " AND LOWER(employee) LIKE ?"
        params.append(f"%{emp_clean}%")

    if category and category.strip():
        query += " AND LOWER(category) = ?"
        params.append(category.strip().lower())

    if expense_type and expense_type.strip().lower() == "travel":
        placeholders = ",".join("?" for _ in travel_categories)
        query += f" AND LOWER(category) IN ({placeholders})"
        params.extend(travel_categories)

    query += " ORDER BY expense_date ASC, id ASC"

    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        results = []
        for r in rows:
            results.append({
                "record_id": r["record_id"],
                "date": r["expense_date"],
                "employee": r["employee"],
                "description": r["description"],
                "merchant": r["merchant"],
                "category": r["category"],
                "amount": float(r["amount"]),
                "receipt_status": r["receipt_status"],
                "receipt_path": r["receipt_path"] or "",
                "source_file": r["source_file"],
            })
        return results
    finally:
        conn.close()


def get_previous_expenses(
    employee: Optional[str] = None,
    limit: int = 100,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve historical transactions for an employee or all employees."""
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    query = "SELECT * FROM expenses WHERE 1=1"
    params: List[Any] = []
    if employee and employee.strip():
        query += " AND LOWER(employee) LIKE ?"
        params.append(f"%{employee.strip().lower()}%")
    query += " ORDER BY expense_date DESC, id DESC LIMIT ?"
    params.append(limit)

    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [
            {
                "record_id": r["record_id"],
                "date": r["expense_date"],
                "employee": r["employee"],
                "description": r["description"],
                "merchant": r["merchant"],
                "category": r["category"],
                "amount": float(r["amount"]),
                "receipt_status": r["receipt_status"],
                "receipt_path": r["receipt_path"] or "",
                "source_file": r["source_file"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def save_validation_issues(
    issues: List[Dict[str, Any]],
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Persist validation findings into the database. Avoids duplicate unresolved
    findings for the same expense record and issue type.
    
    Returns:
        List of saved issue dictionaries enriched with issue_id.
    """
    if not issues:
        return []

    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    saved_issues = []

    try:
        for idx, issue in enumerate(issues):
            exp = issue.get("expense", {})
            rec_id = issue.get("record_id") or exp.get("record_id")
            if not rec_id:
                rec_id = f"EXP-UNKNOWN-{idx}"

            issue_type = issue.get("issue_type", "unknown")
            field_name = issue.get("field_name") or ("receipt_status" if "receipt" in issue_type else "amount")
            message = issue.get("message", "Validation discrepancy detected")
            severity = issue.get("severity", "medium")
            status = issue.get("status", "unresolved")

            # Ensure parent expense record exists to satisfy foreign key constraint
            cursor.execute("SELECT id FROM expenses WHERE record_id = ?", (rec_id,))
            if not cursor.fetchone():
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO expenses (
                        record_id, expense_date, employee, description, merchant,
                        category, amount, receipt_status, receipt_path,
                        source_file, import_hash, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec_id,
                        str(exp.get("date", "2026-01-01")),
                        str(exp.get("employee", "Unknown")),
                        str(exp.get("description", "Unknown")),
                        str(exp.get("merchant", "Unknown")),
                        str(exp.get("category", "Other")),
                        float(exp.get("amount", 0) or 0),
                        str(exp.get("receipt_status", "Missing")),
                        exp.get("receipt_path", ""),
                        "auto_validation",
                        rec_id,
                        now_str,
                        now_str,
                    ),
                )

            # Check if active issue exists for this record and type
            cursor.execute(
                """
                SELECT issue_id, status FROM validation_issues 
                WHERE expense_record_id = ? AND issue_type = ? AND status = 'unresolved'
                """,
                (rec_id, issue_type),
            )
            existing = cursor.fetchone()

            if existing:
                issue_id = existing["issue_id"]
            else:
                issue_id = issue.get("issue_id") or f"ISSUE-{uuid.uuid4().hex[:10]}"
                cursor.execute(
                    """
                    INSERT INTO validation_issues (
                        issue_id, expense_record_id, issue_type, field_name,
                        message, severity, status, detected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        issue_id,
                        rec_id,
                        issue_type,
                        field_name,
                        message,
                        severity,
                        status,
                        now_str,
                    ),
                )

            issue_copy = dict(issue)
            issue_copy["issue_id"] = issue_id
            issue_copy["record_id"] = rec_id
            issue_copy["status"] = status
            saved_issues.append(issue_copy)

        conn.commit()
    finally:
        conn.close()

    return saved_issues


def update_expense_record(
    record_id: str,
    updates: Dict[str, Any],
    db_path: Optional[str] = None,
) -> bool:
    """
    Safely update a stored expense record when a reviewer provides corrections.
    Allowed fields: expense_date, description, merchant, category, amount,
                    receipt_status, receipt_path.
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    field_map = {
        "date": "expense_date",
        "expense_date": "expense_date",
        "description": "description",
        "merchant": "merchant",
        "category": "category",
        "amount": "amount",
        "receipt_status": "receipt_status",
        "receipt_path": "receipt_path",
    }

    set_clauses = []
    params: List[Any] = []

    for k, v in updates.items():
        if k in field_map:
            set_clauses.append(f"{field_map[k]} = ?")
            if field_map[k] == "amount":
                try:
                    params.append(float(v))
                except (ValueError, TypeError):
                    params.append(0.0)
            else:
                params.append(str(v).strip())

    if not set_clauses:
        conn.close()
        return False

    set_clauses.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    params.append(record_id)

    query = f"UPDATE expenses SET {', '.join(set_clauses)} WHERE record_id = ?"

    try:
        cursor.execute(query, params)
        affected = cursor.rowcount > 0
        conn.commit()
        return affected
    finally:
        conn.close()


def resolve_validation_issue(
    issue_id: str,
    decision: str,
    notes: str = "",
    db_path: Optional[str] = None,
) -> bool:
    """
    Update a validation finding's status:
    - 'resolved' (e.g. receipt provided / data corrected)
    - 'accepted_exception' (reviewer accepted with notes)
    - 'excluded' (transaction excluded from report)
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    valid_statuses = {"resolved", "accepted_exception", "excluded", "unresolved"}
    status = decision.lower().strip()
    if status not in valid_statuses:
        status = "accepted_exception" if "accept" in status or "include" in status else "excluded"

    now_str = datetime.now().isoformat()

    try:
        cursor.execute(
            """
            UPDATE validation_issues
            SET status = ?, reviewer_decision = ?, reviewer_notes = ?, resolved_at = ?
            WHERE issue_id = ?
            """,
            (status, decision, notes, now_str, issue_id),
        )
        affected = cursor.rowcount > 0
        conn.commit()
        return affected
    finally:
        conn.close()


def get_unresolved_issues(
    employee: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all open/unresolved issues from memory."""
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    query = """
        SELECT vi.*, e.employee, e.expense_date, e.description, e.merchant, e.amount, e.receipt_status
        FROM validation_issues vi
        JOIN expenses e ON vi.expense_record_id = e.record_id
        WHERE vi.status = 'unresolved'
    """
    params: List[Any] = []
    if employee and employee.strip():
        query += " AND LOWER(e.employee) LIKE ?"
        params.append(f"%{employee.strip().lower()}%")
    query += " ORDER BY vi.id DESC"

    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_report_run(
    report_data: Dict[str, Any],
    db_path: Optional[str] = None,
) -> str:
    """
    Persist an executed report run in SQLite memory.
    
    Args:
        report_data with keys:
            report_id, user_request, filters, transaction_ids,
            transaction_count, grand_total, validation_status,
            report_file_path, human_review_status
            
    Returns:
        report_id: Stable identifier of the report run.
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    report_id = report_data.get("report_id") or f"REP-{uuid.uuid4().hex[:10]}"
    now_str = datetime.now().isoformat()

    try:
        cursor.execute(
            """
            INSERT INTO report_runs (
                report_id, user_request, filters_json, transaction_ids_json,
                transaction_count, grand_total, validation_status,
                report_file_path, human_review_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report_id,
                report_data.get("user_request", ""),
                json.dumps(report_data.get("filters", {})),
                json.dumps(report_data.get("transaction_ids", [])),
                int(report_data.get("transaction_count", 0)),
                float(report_data.get("grand_total", 0.0)),
                report_data.get("validation_status", "Clear"),
                report_data.get("report_file_path", ""),
                report_data.get("human_review_status", "None"),
                now_str,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return report_id


def get_report_history(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve historical report runs from memory."""
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT * FROM report_runs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        results = []
        for r in rows:
            results.append({
                "report_id": r["report_id"],
                "user_request": r["user_request"],
                "filters": json.loads(r["filters_json"] or "{}"),
                "transaction_count": r["transaction_count"],
                "grand_total": r["grand_total"],
                "validation_status": r["validation_status"],
                "report_file_path": r["report_file_path"],
                "human_review_status": r["human_review_status"],
                "created_at": r["created_at"],
            })
        return results
    finally:
        conn.close()


def get_memory_stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve summary counts from persistent memory."""
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) AS total FROM expenses")
        exp_count = cursor.fetchone()["total"]

        cursor.execute("SELECT COUNT(DISTINCT employee) AS emps FROM expenses")
        emp_count = cursor.fetchone()["emps"]

        cursor.execute("SELECT COUNT(*) AS unresolved FROM validation_issues WHERE status = 'unresolved'")
        unresolved_issues = cursor.fetchone()["unresolved"]

        cursor.execute("SELECT COUNT(*) AS total_reports FROM report_runs")
        report_count = cursor.fetchone()["total_reports"]

        return {
            "total_expenses": exp_count,
            "unique_employees": emp_count,
            "unresolved_issues": unresolved_issues,
            "total_reports": report_count,
        }
    finally:
        conn.close()
