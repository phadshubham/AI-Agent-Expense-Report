"""
Persistent SQLite Memory Tools for the AI Expense Report Agent.

Provides long-term storage and retrieval of:
- Datasets master registry and lifecycle management (versioning, hashing, active status)
- Expense records (scoped to dataset_id and version, null-resilient, deduplicated)
- Validation issues and audit resolution history (scoped to dataset_id and version)
- Historical report runs and prompt execution history (scoped to dataset_id)
- Audit events for compliance and modification tracking

Database location: data/expense_memory.db
(Separated cleanly from LangGraph's workflow checkpoint database .checkpoints/agent_state.db)
"""

import os
import sqlite3
import hashlib
import json
import uuid
import math
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple


DEFAULT_MEMORY_DB_PATH = os.path.join("data", "expense_memory.db")
LEGACY_DATASET_ID = "DATASET-LEGACY-UNASSIGNED"


def _sanitize_amount(val: Any, allow_none: bool = True) -> Optional[float]:
    """
    Safely convert any raw amount value to a float or None.
    If allow_none=True, missing, null, or invalid amounts return None (preserving null resilience).
    If allow_none=False, missing or invalid amounts return 0.0 (legacy fallback).
    """
    if val is None:
        return None if allow_none else 0.0
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return None if allow_none else 0.0
        return float(val)
    val_str = str(val).strip()
    if not val_str or val_str.lower() in ("nan", "none", "null", "<na>", ""):
        return None if allow_none else 0.0
    try:
        clean = val_str.replace("₹", "").replace("$", "").replace(",", "").strip()
        num = float(clean)
        if math.isnan(num) or math.isinf(num):
            return None if allow_none else 0.0
        return num
    except (ValueError, TypeError):
        return None if allow_none else 0.0


def _sanitize_text(val: Any, default: str = "") -> str:
    """Safely convert text, converting None / NaN to default string."""
    if val is None:
        return default
    if isinstance(val, float) and math.isnan(val):
        return default
    s = str(val).strip()
    if s.lower() in ("nan", "none", "null", "<na>"):
        return default
    return s


def _sanitize_date(val: Any) -> Optional[str]:
    """
    Safely convert raw date value to YYYY-MM-DD string or None.
    Preserves None when date is missing, empty, or invalid.
    """
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "null", "<na>", ""):
        return None
    if "T" in s:
        s = s.split("T")[0]
    return s


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
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def backup_memory_db(db_path: Optional[str] = None) -> Optional[str]:
    """
    Create a timestamped backup (<basename>_backup_<timestamp>.db) via SQLite online backup API
    if the database exists and contains records before running migration.
    """
    resolved_path = get_db_path(db_path)
    if resolved_path == ":memory:" or not os.path.exists(resolved_path):
        return None

    try:
        conn = sqlite3.connect(resolved_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = cursor.fetchall()
            if not tables:
                return None
            total_records = 0
            for t in tables:
                t_name = t[0]
                try:
                    cnt = cursor.execute(f'SELECT COUNT(*) FROM "{t_name}"').fetchone()[0]
                    total_records += cnt
                except Exception:
                    pass
            if total_records == 0:
                return None
        finally:
            conn.close()
    except Exception:
        return None

    dirname = os.path.dirname(os.path.abspath(resolved_path))
    base_name = os.path.splitext(os.path.basename(resolved_path))[0]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_filename = f"{base_name}_backup_{timestamp}.db"
    backup_path = os.path.join(dirname, backup_filename)

    with sqlite3.connect(resolved_path) as src, sqlite3.connect(backup_path) as dst:
        src.backup(dst)
    return backup_path


def init_memory_db(db_path: Optional[str] = None) -> str:
    """
    Initialize SQLite schema for persistent expense memory (target: user_version = 2).
    Performs safe, idempotent migration from v1 to v2:
    - Pre-migration backup if user_version < 2 and database has records
    - Disables foreign keys during table rebuild
    - Creates datasets master table and seeds master record DATASET-LEGACY-UNASSIGNED
    - Creates expenses_v2 (nullable amount and expense_date, dataset_id, dataset_version, location, is_excluded)
    - Migrates existing expenses tagged to DATASET-LEGACY-UNASSIGNED, version 1
    - Creates validation_issues_v2 and report_runs_v2 tagged to legacy dataset
    - Recreates audit_events with dataset_id
    - Drops old tables and creates backward-compatible views and INSTEAD OF triggers
    - Verifies zero foreign key violations
    - Sets PRAGMA user_version = 2
    """
    path = get_db_path(db_path)
    if path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    # Check existing user_version before opening active connection
    user_version = 0
    if path != ":memory:" and os.path.exists(path):
        temp_conn = sqlite3.connect(path)
        try:
            user_version = temp_conn.execute("PRAGMA user_version;").fetchone()[0]
        except Exception:
            user_version = 0
        finally:
            temp_conn.close()

    # Pre-migration backup if needed
    if user_version < 2 and path != ":memory:" and os.path.exists(path):
        backup_memory_db(path)

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # Autocommit mode for explicit transaction control
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA user_version;")
        current_ver = cursor.fetchone()[0]

        if current_ver < 2:
            cursor.execute("PRAGMA foreign_keys = OFF;")
            cursor.execute("BEGIN TRANSACTION;")

            # 1. Datasets Master Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    row_count INTEGER NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    schema_json TEXT NOT NULL DEFAULT '{}',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_datasets_hash ON datasets(file_hash);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_datasets_active ON datasets(is_active);")

            # Check existing objects to migrate
            cursor.execute("SELECT name, type FROM sqlite_master WHERE name IN ('expenses', 'validation_issues', 'report_runs', 'audit_events')")
            existing_objects = {row[0]: row[1] for row in cursor.fetchall()}

            legacy_expense_count = 0
            if existing_objects.get("expenses") == "table":
                cursor.execute("SELECT COUNT(*) FROM expenses")
                legacy_expense_count = cursor.fetchone()[0]

            now_str = datetime.now(timezone.utc).isoformat()

            # 2. Insert master legacy record
            cursor.execute("""
                INSERT OR IGNORE INTO datasets (
                    dataset_id, name, file_hash, row_count, version, schema_json, is_active, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                );
            """, (
                LEGACY_DATASET_ID,
                "Legacy Unassigned Ingested Data",
                "legacy-pre-migration",
                legacy_expense_count,
                1,
                '{"columns": ["record_id", "date", "employee", "description", "merchant", "category", "amount", "receipt_status", "receipt_path"]}',
                0,
                now_str,
                now_str,
            ))

            # 3. Expenses V2 Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS expenses_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    dataset_version INTEGER NOT NULL DEFAULT 1,
                    expense_date TEXT,
                    employee TEXT NOT NULL DEFAULT 'Unknown',
                    description TEXT NOT NULL DEFAULT 'Unknown',
                    merchant TEXT NOT NULL DEFAULT 'Unknown',
                    category TEXT NOT NULL DEFAULT 'Other',
                    amount REAL,
                    receipt_status TEXT NOT NULL DEFAULT 'Missing',
                    receipt_path TEXT,
                    location TEXT,
                    payment_method TEXT,
                    is_excluded INTEGER NOT NULL DEFAULT 0,
                    source_file TEXT NOT NULL,
                    import_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(dataset_id, dataset_version, record_id),
                    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id) ON DELETE CASCADE
                );
            """)

            # 4. Migrate existing expenses if expenses was a table
            if existing_objects.get("expenses") == "table":
                cursor.execute(f"""
                    INSERT OR IGNORE INTO expenses_v2 (
                        record_id, dataset_id, dataset_version, expense_date, employee,
                        description, merchant, category, amount, receipt_status,
                        receipt_path, location, payment_method, is_excluded,
                        source_file, import_hash, created_at, updated_at
                    )
                    SELECT 
                        record_id,
                        '{LEGACY_DATASET_ID}',
                        1,
                        NULLIF(expense_date, ''),
                        employee,
                        description,
                        merchant,
                        category,
                        amount,
                        receipt_status,
                        receipt_path,
                        NULL,
                        NULL,
                        0,
                        source_file,
                        import_hash,
                        created_at,
                        updated_at
                    FROM expenses;
                """)

            # 5. Validation Issues V2 Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS validation_issues_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_id TEXT UNIQUE NOT NULL,
                    dataset_id TEXT NOT NULL,
                    dataset_version INTEGER NOT NULL DEFAULT 1,
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
                    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id) ON DELETE CASCADE
                );
            """)

            # 6. Migrate existing validation issues if table
            if existing_objects.get("validation_issues") == "table":
                cursor.execute(f"""
                    INSERT OR IGNORE INTO validation_issues_v2 (
                        issue_id, dataset_id, dataset_version, expense_record_id,
                        issue_type, field_name, message, severity, status,
                        detected_at, resolved_at, reviewer_decision, reviewer_notes
                    )
                    SELECT 
                        issue_id,
                        '{LEGACY_DATASET_ID}',
                        1,
                        expense_record_id,
                        issue_type,
                        field_name,
                        message,
                        severity,
                        status,
                        detected_at,
                        resolved_at,
                        reviewer_decision,
                        reviewer_notes
                    FROM validation_issues;
                """)

            # 7. Report Runs V2 Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS report_runs_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT UNIQUE NOT NULL,
                    report_id TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    dataset_version INTEGER NOT NULL DEFAULT 1,
                    user_request TEXT NOT NULL,
                    filters_json TEXT NOT NULL,
                    transaction_ids_json TEXT NOT NULL,
                    transaction_count INTEGER NOT NULL,
                    grand_total REAL NOT NULL,
                    validation_status TEXT NOT NULL,
                    report_file_path TEXT NOT NULL,
                    human_review_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id) ON DELETE CASCADE
                );
            """)

            # 8. Migrate existing report runs if table
            if existing_objects.get("report_runs") == "table":
                cursor.execute(f"""
                    INSERT OR IGNORE INTO report_runs_v2 (
                        run_id, report_id, dataset_id, dataset_version,
                        user_request, filters_json, transaction_ids_json,
                        transaction_count, grand_total, validation_status,
                        report_file_path, human_review_status, created_at
                    )
                    SELECT 
                        'RUN-' || report_id,
                        report_id,
                        '{LEGACY_DATASET_ID}',
                        1,
                        user_request,
                        filters_json,
                        transaction_ids_json,
                        transaction_count,
                        grand_total,
                        validation_status,
                        report_file_path,
                        human_review_status,
                        created_at
                    FROM report_runs;
                """)

            # 9. Recreate audit_events table with dataset_id
            if existing_objects.get("audit_events") == "table":
                cursor.execute("DROP TABLE audit_events;")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    dataset_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id) ON DELETE CASCADE
                );
            """)

            # Import Batches Table
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

            # 10. Drop old tables if they were tables
            if existing_objects.get("expenses") == "table":
                cursor.execute("DROP TABLE expenses;")
            if existing_objects.get("validation_issues") == "table":
                cursor.execute("DROP TABLE validation_issues;")
            if existing_objects.get("report_runs") == "table":
                cursor.execute("DROP TABLE report_runs;")

            # 11. Create Backward-Compatibility Views
            cursor.execute("""
                CREATE VIEW IF NOT EXISTS expenses AS 
                SELECT 
                    id, record_id, dataset_id, dataset_version, expense_date, employee, 
                    description, merchant, category, amount, receipt_status, receipt_path, 
                    location, payment_method, is_excluded, source_file, import_hash, 
                    created_at, updated_at 
                FROM expenses_v2;
            """)

            cursor.execute("""
                CREATE VIEW IF NOT EXISTS validation_issues AS 
                SELECT 
                    id, issue_id, dataset_id, dataset_version, expense_record_id, 
                    issue_type, field_name, message, severity, status, 
                    detected_at, resolved_at, reviewer_decision, reviewer_notes 
                FROM validation_issues_v2;
            """)

            cursor.execute("""
                CREATE VIEW IF NOT EXISTS report_runs AS 
                SELECT 
                    id, run_id, report_id, dataset_id, dataset_version, user_request, 
                    filters_json, transaction_ids_json, transaction_count, grand_total, 
                    validation_status, report_file_path, human_review_status, created_at 
                FROM report_runs_v2;
            """)

            # 12. Create INSTEAD OF Triggers on Views
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_expenses_insert INSTEAD OF INSERT ON expenses
                BEGIN
                    INSERT INTO expenses_v2 (
                        record_id, dataset_id, dataset_version, expense_date, employee,
                        description, merchant, category, amount, receipt_status,
                        receipt_path, location, payment_method, is_excluded,
                        source_file, import_hash, created_at, updated_at
                    ) VALUES (
                        NEW.record_id,
                        COALESCE(NEW.dataset_id, (SELECT dataset_id FROM datasets WHERE is_active = 1 LIMIT 1), 'DATASET-LEGACY-UNASSIGNED'),
                        COALESCE(NEW.dataset_version, 1),
                        NEW.expense_date, NEW.employee, NEW.description, NEW.merchant,
                        NEW.category, NEW.amount, NEW.receipt_status, NEW.receipt_path,
                        NEW.location, NEW.payment_method, COALESCE(NEW.is_excluded, 0),
                        NEW.source_file, NEW.import_hash, NEW.created_at, NEW.updated_at
                    );
                END;
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_expenses_update INSTEAD OF UPDATE ON expenses
                BEGIN
                    UPDATE expenses_v2 SET
                        expense_date = NEW.expense_date,
                        employee = NEW.employee,
                        description = NEW.description,
                        merchant = NEW.merchant,
                        category = NEW.category,
                        amount = NEW.amount,
                        receipt_status = NEW.receipt_status,
                        receipt_path = NEW.receipt_path,
                        location = NEW.location,
                        is_excluded = NEW.is_excluded,
                        updated_at = NEW.updated_at
                    WHERE record_id = OLD.record_id;
                END;
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_expenses_delete INSTEAD OF DELETE ON expenses
                BEGIN
                    DELETE FROM expenses_v2 WHERE record_id = OLD.record_id;
                END;
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_val_issues_insert INSTEAD OF INSERT ON validation_issues
                BEGIN
                    INSERT INTO validation_issues_v2 (
                        issue_id, dataset_id, dataset_version, expense_record_id,
                        issue_type, field_name, message, severity, status,
                        detected_at, resolved_at, reviewer_decision, reviewer_notes
                    ) VALUES (
                        NEW.issue_id,
                        COALESCE(NEW.dataset_id, (SELECT dataset_id FROM datasets WHERE is_active = 1 LIMIT 1), 'DATASET-LEGACY-UNASSIGNED'),
                        COALESCE(NEW.dataset_version, 1),
                        NEW.expense_record_id,
                        NEW.issue_type, NEW.field_name, NEW.message, NEW.severity,
                        COALESCE(NEW.status, 'unresolved'),
                        NEW.detected_at, NEW.resolved_at, NEW.reviewer_decision, NEW.reviewer_notes
                    );
                END;
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_val_issues_update INSTEAD OF UPDATE ON validation_issues
                BEGIN
                    UPDATE validation_issues_v2 SET
                        status = NEW.status,
                        reviewer_decision = NEW.reviewer_decision,
                        reviewer_notes = NEW.reviewer_notes,
                        resolved_at = NEW.resolved_at
                    WHERE issue_id = OLD.issue_id;
                END;
            """)

            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS trg_report_runs_insert INSTEAD OF INSERT ON report_runs
                BEGIN
                    INSERT INTO report_runs_v2 (
                        run_id, report_id, dataset_id, dataset_version,
                        user_request, filters_json, transaction_ids_json,
                        transaction_count, grand_total, validation_status,
                        report_file_path, human_review_status, created_at
                    ) VALUES (
                        COALESCE(NEW.run_id, 'RUN-' || NEW.report_id),
                        NEW.report_id,
                        COALESCE(NEW.dataset_id, (SELECT dataset_id FROM datasets WHERE is_active = 1 LIMIT 1), 'DATASET-LEGACY-UNASSIGNED'),
                        COALESCE(NEW.dataset_version, 1),
                        NEW.user_request, NEW.filters_json, NEW.transaction_ids_json,
                        NEW.transaction_count, NEW.grand_total, NEW.validation_status,
                        NEW.report_file_path, NEW.human_review_status, NEW.created_at
                    );
                END;
            """)

            # 13. Create Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exp_v2_dataset ON expenses_v2(dataset_id, dataset_version);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exp_v2_date ON expenses_v2(dataset_id, expense_date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exp_v2_employee ON expenses_v2(dataset_id, employee);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_exp_v2_rec ON expenses_v2(record_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_val_v2_dataset ON validation_issues_v2(dataset_id, dataset_version);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_val_v2_status ON validation_issues_v2(dataset_id, status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_val_v2_exp ON validation_issues_v2(expense_record_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rep_v2_dataset ON report_runs_v2(dataset_id, dataset_version);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_rep_v2_created ON report_runs_v2(created_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_dataset ON audit_events(dataset_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_events(created_at);")

            # 14. Update user_version
            cursor.execute("PRAGMA user_version = 2;")
            cursor.execute("COMMIT;")

            # 15. Verify foreign key integrity
            cursor.execute("PRAGMA foreign_keys = ON;")
            fk_errors = cursor.execute("PRAGMA foreign_key_check;").fetchall()
            if fk_errors:
                raise RuntimeError(f"Foreign key violations detected after migration: {fk_errors}")

    finally:
        conn.close()

    return path


# =====================================================================
# Dataset Master & Lifecycle APIs
# =====================================================================

def create_or_get_dataset(
    name: str,
    file_hash: str,
    row_count: int,
    schema: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Register or fetch a dataset, activating it by default and deactivating all others.
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    schema_json = json.dumps(schema or {})
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute("SELECT * FROM datasets WHERE file_hash = ?", (file_hash,))
        row = cursor.fetchone()
        if row:
            dataset_id = row["dataset_id"]
            cursor.execute("UPDATE datasets SET is_active = 0 WHERE dataset_id != ?", (dataset_id,))
            cursor.execute("UPDATE datasets SET is_active = 1, updated_at = ? WHERE dataset_id = ?", (now_str, dataset_id))
            conn.commit()
            return {
                "dataset_id": row["dataset_id"],
                "name": row["name"],
                "file_hash": row["file_hash"],
                "row_count": row["row_count"],
                "version": row["version"],
                "schema": json.loads(row["schema_json"] or "{}"),
                "is_active": 1,
                "created_at": row["created_at"],
                "updated_at": now_str,
            }

        dataset_id = f"DS-{uuid.uuid4().hex[:10]}"
        cursor.execute("UPDATE datasets SET is_active = 0")
        cursor.execute("""
            INSERT INTO datasets (
                dataset_id, name, file_hash, row_count, version, schema_json, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            dataset_id, name, file_hash, row_count, 1, schema_json, 1, now_str, now_str
        ))
        conn.commit()

        save_audit_event(
            dataset_id=dataset_id,
            event_type="dataset_created",
            entity_type="dataset",
            entity_id=dataset_id,
            details={"name": name, "file_hash": file_hash, "row_count": row_count, "version": 1},
            db_path=db_path,
        )

        return {
            "dataset_id": dataset_id,
            "name": name,
            "file_hash": file_hash,
            "row_count": row_count,
            "version": 1,
            "schema": schema or {},
            "is_active": 1,
            "created_at": now_str,
            "updated_at": now_str,
        }
    finally:
        conn.close()


def set_active_dataset(dataset_id: str, db_path: Optional[str] = None) -> bool:
    """
    Set specified dataset as active (is_active=1) and all others inactive (is_active=0).
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute("SELECT dataset_id FROM datasets WHERE dataset_id = ?", (dataset_id,))
        if not cursor.fetchone():
            return False
        cursor.execute("UPDATE datasets SET is_active = 0 WHERE dataset_id != ?", (dataset_id,))
        cursor.execute("UPDATE datasets SET is_active = 1, updated_at = ? WHERE dataset_id = ?", (now_str, dataset_id))
        conn.commit()

        save_audit_event(
            dataset_id=dataset_id,
            event_type="dataset_activated",
            entity_type="dataset",
            entity_id=dataset_id,
            details={"activated_at": now_str},
            db_path=db_path,
        )
        return True
    finally:
        conn.close()


def get_active_dataset(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Return current active dataset dictionary or None if no dataset is active.
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM datasets WHERE is_active = 1 LIMIT 1")
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "dataset_id": row["dataset_id"],
            "name": row["name"],
            "file_hash": row["file_hash"],
            "row_count": row["row_count"],
            "version": row["version"],
            "schema": json.loads(row["schema_json"] or "{}"),
            "is_active": row["is_active"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def list_datasets(db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List all registered datasets in the master registry, ordered with active dataset first.
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM datasets ORDER BY is_active DESC, updated_at DESC")
        rows = cursor.fetchall()
        return [
            {
                "dataset_id": r["dataset_id"],
                "name": r["name"],
                "file_hash": r["file_hash"],
                "row_count": r["row_count"],
                "version": r["version"],
                "schema": json.loads(r["schema_json"] or "{}"),
                "is_active": r["is_active"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_dataset(dataset_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieve details for a single dataset by its dataset_id.
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "dataset_id": row["dataset_id"],
            "name": row["name"],
            "file_hash": row["file_hash"],
            "row_count": row["row_count"],
            "version": row["version"],
            "schema": json.loads(row["schema_json"] or "{}"),
            "is_active": row["is_active"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def increment_dataset_version(
    dataset_id: str,
    updated_records: List[Dict[str, Any]],
    db_path: Optional[str] = None,
) -> int:
    """
    Persist updated records under a new dataset version, bump dataset version in master registry,
    and log an immutable audit event.
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute("SELECT version, name FROM datasets WHERE dataset_id = ?", (dataset_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Dataset {dataset_id} not found")
        current_version = row["version"]
        new_version = current_version + 1

        cursor.execute(
            "UPDATE datasets SET version = ?, row_count = ?, updated_at = ? WHERE dataset_id = ?",
            (new_version, len(updated_records), now_str, dataset_id),
        )
        conn.commit()
    finally:
        conn.close()

    save_expenses(
        expenses=updated_records,
        dataset_id=dataset_id,
        dataset_version=new_version,
        source_name=row["name"],
        db_path=db_path,
    )

    save_audit_event(
        dataset_id=dataset_id,
        event_type="dataset_version_incremented",
        entity_type="dataset",
        entity_id=dataset_id,
        details={
            "old_version": current_version,
            "new_version": new_version,
            "record_count": len(updated_records),
        },
        db_path=db_path,
    )
    return new_version


# =====================================================================
# Audit Event APIs
# =====================================================================

def _ensure_dataset_registered(
    cursor: sqlite3.Cursor,
    dataset_id: str,
    dataset_version: Optional[int] = 1,
    row_count: int = 0,
) -> int:
    """Ensure dataset_id exists in datasets table to satisfy foreign keys. Returns latest version."""
    cursor.execute("SELECT version FROM datasets WHERE dataset_id = ?", (dataset_id,))
    row = cursor.fetchone()
    if row:
        return row[0]
    ver = dataset_version if dataset_version is not None else 1
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        """
        INSERT OR IGNORE INTO datasets (dataset_id, name, file_hash, row_count, version, schema_json, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (dataset_id, f"Dataset {dataset_id}", f"auto-{dataset_id}", row_count, ver, "{}", 1, now_iso, now_iso),
    )
    return ver


def save_audit_event(
    dataset_id: str,
    event_type: str,
    entity_type: str,
    entity_id: str,
    details: Dict[str, Any],
    db_path: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """
    Record an immutable compliance and change audit event.
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    _ensure_dataset_registered(cursor, dataset_id)
    event_id = f"AUD-{uuid.uuid4().hex[:10]}"
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute("""
            INSERT INTO audit_events (
                event_id, dataset_id, event_type, entity_type, entity_id, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id,
            dataset_id,
            event_type,
            entity_type,
            entity_id,
            json.dumps(details),
            now_str,
        ))
        conn.commit()
        return event_id
    finally:
        conn.close()


def get_audit_events(
    dataset_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = 100,
    db_path: Optional[str] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """
    Retrieve audit events, optionally filtered by dataset_id and entity_id.
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    query = "SELECT * FROM audit_events WHERE 1=1"
    params: List[Any] = []
    if dataset_id:
        query += " AND dataset_id = ?"
        params.append(dataset_id)
    if entity_id:
        query += " AND entity_id = ?"
        params.append(entity_id)
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [
            {
                "event_id": r["event_id"],
                "dataset_id": r["dataset_id"],
                "event_type": r["event_type"],
                "entity_type": r["entity_type"],
                "entity_id": r["entity_id"],
                "details": json.loads(r["details_json"] or "{}"),
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


# =====================================================================
# Expense Persistence & Scoped Retrieval
# =====================================================================

def _generate_record_id(record: Dict[str, Any], source: str, row_idx: int) -> str:
    """Generate a deterministic record identifier."""
    val_str = f"{source}:{row_idx}:{_sanitize_text(record.get('employee', ''))}:{_sanitize_text(record.get('date', ''))}:{_sanitize_text(record.get('merchant', ''))}:{_sanitize_amount(record.get('amount', 0), allow_none=False)}"
    h = hashlib.sha256(val_str.encode("utf-8")).hexdigest()[:12]
    return f"EXP-{h}"


def _compute_import_hash(source_name: str, expenses: List[Dict[str, Any]]) -> str:
    """Compute a cryptographic hash of the entire dataset import."""
    serialized = json.dumps(
        [
            {
                "e": _sanitize_text(x.get("employee", "")),
                "d": _sanitize_text(x.get("date", "") if x.get("date") is not None else x.get("expense_date", "")),
                "m": _sanitize_text(x.get("merchant", "")),
                "a": _sanitize_amount(x.get("amount", 0), allow_none=False),
                "c": _sanitize_text(x.get("category", "")),
            }
            for x in expenses
        ],
        sort_keys=True,
    )
    return hashlib.sha256(f"{source_name}:{serialized}".encode("utf-8")).hexdigest()


def save_expenses(
    expenses: List[Dict[str, Any]],
    dataset_id: Optional[str] = None,
    dataset_version: Optional[int] = None,
    source_name: str = "expenses.csv",
    db_path: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Persistently store expense records in SQLite memory with dataset scoping and deduplication.
    
    If dataset_id is None, falls back to active dataset or DATASET-LEGACY-UNASSIGNED.
    Preserves raw null values in amount and expense_date.
    
    Returns standard dictionary for compatibility with agent.py, app.py, and test suites:
        dict: {
            "batch_id": str,
            "total_processed": int,
            "inserted": int,
            "skipped_duplicates": int,
            "records": List[dict],
            "dataset_id": str,
            "dataset_version": int,
        }
    """
    if not expenses:
        return {
            "batch_id": "",
            "total_processed": 0,
            "inserted": 0,
            "skipped_duplicates": 0,
            "records": [],
            "dataset_id": dataset_id or "",
            "dataset_version": dataset_version or 1,
        }

    init_memory_db(db_path)

    # Scoping fallback
    if dataset_id is None:
        active = get_active_dataset(db_path)
        if active:
            dataset_id = active["dataset_id"]
            if dataset_version is None:
                dataset_version = active.get("version", 1)
        else:
            dataset_id = LEGACY_DATASET_ID
            if dataset_version is None:
                dataset_version = 1

    conn = get_connection(db_path)
    cursor = conn.cursor()
    dataset_version = _ensure_dataset_registered(cursor, dataset_id, dataset_version, len(expenses))

    file_hash = _compute_import_hash(source_name, expenses)
    now_str = datetime.now(timezone.utc).isoformat()
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

            # Null-resilient sanitization
            exp_date = _sanitize_date(exp.get("date") if exp.get("date") is not None else exp.get("expense_date"))
            amt = _sanitize_amount(exp.get("amount"), allow_none=True)

            emp_name = _sanitize_text(exp.get("employee", "Unknown"), default="Unknown") or "Unknown"
            desc = _sanitize_text(exp.get("description", "Unknown"), default="Unknown") or "Unknown"
            merchant = _sanitize_text(exp.get("merchant", "Unknown"), default="Unknown") or "Unknown"
            category = _sanitize_text(exp.get("category", "Other"), default="Other") or "Other"
            receipt_status = _sanitize_text(exp.get("receipt_status", "Verified"), default="Verified") or "Verified"
            receipt_path = _sanitize_text(exp.get("receipt_path", ""))

            # Case-insensitive location extraction (location, city, destination)
            raw_loc = None
            for loc_target in ("location", "city", "destination"):
                for k, v in exp.items():
                    if str(k).strip().lower() == loc_target:
                        if v is not None and str(v).strip() not in ("", "nan", "null", "none", "None"):
                            raw_loc = v
                            break
                if raw_loc is not None:
                    break
            location = _sanitize_text(raw_loc) or None

            payment_method = _sanitize_text(exp.get("payment_method", "")) or None
            is_excluded = 1 if exp.get("is_excluded") in (1, True, "1", "true") else 0

            # Check if this record_id already exists in expenses_v2 for this dataset and version
            cursor.execute(
                "SELECT id, is_excluded FROM expenses_v2 WHERE dataset_id = ? AND dataset_version = ? AND record_id = ?",
                (dataset_id, dataset_version, rec_id),
            )
            exists = cursor.fetchone()

            if exists:
                skipped_count += 1
                if "is_excluded" not in exp:
                    is_excluded = exists["is_excluded"]
            else:
                cursor.execute(
                    """
                    INSERT INTO expenses_v2 (
                        record_id, dataset_id, dataset_version, expense_date, employee,
                        description, merchant, category, amount, receipt_status,
                        receipt_path, location, payment_method, is_excluded,
                        source_file, import_hash, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec_id,
                        dataset_id,
                        dataset_version,
                        exp_date,
                        emp_name,
                        desc,
                        merchant,
                        category,
                        amt,
                        receipt_status,
                        receipt_path,
                        location,
                        payment_method,
                        is_excluded,
                        source_name,
                        file_hash,
                        now_str,
                        now_str,
                    ),
                )
                inserted_count += 1

            enriched_records.append({
                "record_id": rec_id,
                "dataset_id": dataset_id,
                "dataset_version": dataset_version,
                "date": exp_date,
                "expense_date": exp_date,
                "employee": emp_name,
                "description": desc,
                "merchant": merchant,
                "category": category,
                "amount": amt,
                "receipt_status": receipt_status,
                "receipt_path": receipt_path,
                "location": location,
                "payment_method": payment_method,
                "is_excluded": is_excluded,
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
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
    }


def retrieve_expenses_from_db(
    dataset_id: Optional[str] = None,
    dataset_version: Optional[int] = None,
    employee: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    expense_type: Optional[str] = None,
    location: Optional[str] = None,
    merchant: Optional[str] = None,
    include_excluded: bool = False,
    filters: Optional[Dict[str, Any]] = None,
    graceful_location: bool = True,
    db_path: Optional[str] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """
    Retrieve stored expense records with strict dataset isolation and parameterized filtering.
    
    If dataset_id is None: queries active dataset, or all records if no active dataset exists.
    Preserves raw null amounts safely without TypeError.
    """
    init_memory_db(db_path)

    if filters:
        if "employee" in filters:
            employee = filters["employee"]
        elif "employee_name" in filters:
            employee = filters["employee_name"]
        if "start_date" in filters:
            start_date = filters["start_date"]
        if "end_date" in filters:
            end_date = filters["end_date"]
        if "category" in filters:
            category = filters["category"]
        if "expense_type" in filters:
            expense_type = filters["expense_type"]
        if "location" in filters:
            location = filters["location"]
        if "merchant" in filters:
            merchant = filters["merchant"]
        if "include_excluded" in filters:
            include_excluded = filters["include_excluded"]
        if not dataset_id and filters.get("dataset_id"):
            dataset_id = filters["dataset_id"]
        if dataset_version is None and filters.get("dataset_version"):
            dataset_version = filters["dataset_version"]

    # Scoping resolution
    if dataset_id is None:
        active = get_active_dataset(db_path)
        if active:
            dataset_id = active["dataset_id"]
            if dataset_version is None:
                dataset_version = active.get("version", 1)
    elif dataset_version is None:
        conn_tmp = get_connection(db_path)
        try:
            row = conn_tmp.execute("SELECT version FROM datasets WHERE dataset_id = ?", (dataset_id,)).fetchone()
            if row:
                dataset_version = row["version"]
        finally:
            conn_tmp.close()

    conn = get_connection(db_path)
    cursor = conn.cursor()

    travel_categories = ["flight", "transport", "accommodation", "meals"]
    query = "SELECT * FROM expenses_v2 WHERE 1=1"
    params: List[Any] = []

    if dataset_id:
        query += " AND dataset_id = ?"
        params.append(dataset_id)
        if dataset_version is not None:
            query += " AND dataset_version = ?"
            params.append(dataset_version)

    if not include_excluded:
        query += " AND is_excluded = 0"

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

    if merchant and merchant.strip():
        query += " AND LOWER(merchant) LIKE ?"
        params.append(f"%{merchant.strip().lower()}%")

    if location and location.strip():
        loc_supported = True
        if dataset_id and graceful_location:
            cursor.execute(
                "SELECT 1 FROM expenses_v2 WHERE dataset_id = ? AND location IS NOT NULL AND TRIM(location) != '' LIMIT 1",
                (dataset_id,)
            )
            loc_supported = cursor.fetchone() is not None
        elif graceful_location:
            cursor.execute(
                "SELECT 1 FROM expenses_v2 WHERE location IS NOT NULL AND TRIM(location) != '' LIMIT 1"
            )
            loc_supported = cursor.fetchone() is not None

        if loc_supported:
            query += " AND LOWER(location) = ?"
            params.append(location.strip().lower())

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
            amt = float(r["amount"]) if r["amount"] is not None else None
            results.append({
                "record_id": r["record_id"],
                "dataset_id": r["dataset_id"],
                "dataset_version": r["dataset_version"],
                "date": r["expense_date"],
                "expense_date": r["expense_date"],
                "employee": r["employee"],
                "description": r["description"],
                "merchant": r["merchant"],
                "category": r["category"],
                "amount": amt,
                "receipt_status": r["receipt_status"],
                "receipt_path": r["receipt_path"] or "",
                "location": r["location"],
                "payment_method": r["payment_method"],
                "is_excluded": r["is_excluded"],
                "source_file": r["source_file"],
            })
        return results
    finally:
        conn.close()


def dataset_has_location_support(dataset_id: str, db_path: Optional[str] = None) -> bool:
    """Return True if the dataset contains at least one non-null, non-empty location value."""
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM expenses_v2 WHERE dataset_id = ? AND location IS NOT NULL AND TRIM(location) != '' LIMIT 1",
            (dataset_id,)
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


def get_previous_expenses(
    employee: Optional[str] = None,
    limit: int = 100,
    dataset_id: Optional[str] = None,
    dataset_version: Optional[int] = None,
    db_path: Optional[str] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Retrieve historical transactions scoped to dataset."""
    init_memory_db(db_path)

    if dataset_id is None:
        active = get_active_dataset(db_path)
        if active:
            dataset_id = active["dataset_id"]
            if dataset_version is None:
                dataset_version = active.get("version", 1)

    conn = get_connection(db_path)
    cursor = conn.cursor()

    query = "SELECT * FROM expenses_v2 WHERE is_excluded = 0"
    params: List[Any] = []

    if dataset_id:
        query += " AND dataset_id = ?"
        params.append(dataset_id)
        if dataset_version is not None:
            query += " AND dataset_version = ?"
            params.append(dataset_version)

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
                "dataset_id": r["dataset_id"],
                "dataset_version": r["dataset_version"],
                "date": r["expense_date"],
                "expense_date": r["expense_date"],
                "employee": r["employee"],
                "description": r["description"],
                "merchant": r["merchant"],
                "category": r["category"],
                "amount": float(r["amount"]) if r["amount"] is not None else None,
                "receipt_status": r["receipt_status"],
                "receipt_path": r["receipt_path"] or "",
                "location": r["location"],
                "payment_method": r["payment_method"],
                "is_excluded": r["is_excluded"],
                "source_file": r["source_file"],
            }
            for r in rows
        ]
    finally:
        conn.close()


# =====================================================================
# Validation Issues & Reviewer Decisions
# =====================================================================

def save_validation_issues(
    issues: List[Dict[str, Any]],
    dataset_id: Optional[str] = None,
    dataset_version: Optional[int] = None,
    db_path: Optional[str] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """
    Persist validation findings into validation_issues_v2 scoped to dataset_id and version.
    Avoids duplicate unresolved findings for the same expense record and issue type.
    """
    if not issues:
        return []

    init_memory_db(db_path)

    if dataset_id is None:
        active = get_active_dataset(db_path)
        if active:
            dataset_id = active["dataset_id"]
            if dataset_version is None:
                dataset_version = active.get("version", 1)
        else:
            dataset_id = LEGACY_DATASET_ID
            if dataset_version is None:
                dataset_version = 1

    conn = get_connection(db_path)
    cursor = conn.cursor()
    dataset_version = _ensure_dataset_registered(cursor, dataset_id, dataset_version, len(issues))
    now_str = datetime.now(timezone.utc).isoformat()
    saved_issues = []

    try:
        for idx, issue in enumerate(issues):
            exp = issue.get("expense", {})
            rec_id = issue.get("record_id") or issue.get("expense_record_id") or exp.get("record_id")
            if not rec_id:
                rec_id = f"EXP-UNKNOWN-{idx}"

            issue_type = issue.get("issue_type", "unknown")
            field_name = issue.get("field_name") or ("receipt_status" if "receipt" in issue_type else "amount")
            message = issue.get("message", "Validation discrepancy detected")
            severity = issue.get("severity", "medium")
            status = issue.get("status", "unresolved")

            # Ensure parent expense record exists in expenses_v2
            cursor.execute(
                "SELECT id FROM expenses_v2 WHERE dataset_id = ? AND dataset_version = ? AND record_id = ?",
                (dataset_id, dataset_version, rec_id),
            )
            if not cursor.fetchone():
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO expenses_v2 (
                        record_id, dataset_id, dataset_version, expense_date, employee,
                        description, merchant, category, amount, receipt_status,
                        receipt_path, location, payment_method, is_excluded,
                        source_file, import_hash, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rec_id,
                        dataset_id,
                        dataset_version,
                        _sanitize_date(exp.get("date") or exp.get("expense_date") or "2026-01-01"),
                        _sanitize_text(exp.get("employee", "Unknown"), default="Unknown"),
                        _sanitize_text(exp.get("description", "Unknown"), default="Unknown"),
                        _sanitize_text(exp.get("merchant", "Unknown"), default="Unknown"),
                        _sanitize_text(exp.get("category", "Other"), default="Other"),
                        _sanitize_amount(exp.get("amount"), allow_none=True),
                        _sanitize_text(exp.get("receipt_status", "Missing"), default="Missing"),
                        _sanitize_text(exp.get("receipt_path", "")),
                        _sanitize_text(exp.get("location") or exp.get("city", "")) or None,
                        _sanitize_text(exp.get("payment_method", "")) or None,
                        0,
                        "auto_validation",
                        rec_id,
                        now_str,
                        now_str,
                    ),
                )

            # Check if parent expense record is marked is_excluded = 1
            cursor.execute(
                "SELECT is_excluded FROM expenses_v2 WHERE dataset_id = ? AND record_id = ?",
                (dataset_id, rec_id),
            )
            exp_parent = cursor.fetchone()
            is_parent_excluded = bool(exp_parent and exp_parent["is_excluded"] == 1)

            # Check if an issue already exists for this record and type (unresolved, accepted_exception, excluded, or resolved)
            cursor.execute(
                """
                SELECT issue_id, status, reviewer_decision, reviewer_notes FROM validation_issues_v2 
                WHERE dataset_id = ? AND expense_record_id = ? AND issue_type = ?
                ORDER BY id DESC LIMIT 1
                """,
                (dataset_id, rec_id, issue_type),
            )
            existing = cursor.fetchone()

            if not existing:
                # Also check if any issue for this record in this dataset was already resolved/accepted/excluded
                cursor.execute(
                    """
                    SELECT issue_id, status, reviewer_decision, reviewer_notes FROM validation_issues_v2 
                    WHERE dataset_id = ? AND expense_record_id = ? AND status IN ('accepted_exception', 'excluded', 'resolved')
                    ORDER BY id DESC LIMIT 1
                    """,
                    (dataset_id, rec_id),
                )
                existing = cursor.fetchone()

            if is_parent_excluded:
                issue_id = existing["issue_id"] if existing else (issue.get("issue_id") or f"ISSUE-{uuid.uuid4().hex[:10]}")
                current_status = "excluded"
                rev_decision = "exclude"
                rev_notes = (existing["reviewer_notes"] if existing else None) or "Excluded by reviewer"
            elif existing:
                issue_id = existing["issue_id"]
                current_status = existing["status"]
                rev_decision = existing["reviewer_decision"]
                rev_notes = existing["reviewer_notes"]
            else:
                issue_id = issue.get("issue_id") or f"ISSUE-{uuid.uuid4().hex[:10]}"
                current_status = issue.get("status", "unresolved")
                rev_decision = issue.get("reviewer_decision")
                rev_notes = issue.get("reviewer_notes")
                cursor.execute(
                    """
                    INSERT INTO validation_issues_v2 (
                        issue_id, dataset_id, dataset_version, expense_record_id,
                        issue_type, field_name, message, severity, status, detected_at,
                        reviewer_decision, reviewer_notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        issue_id,
                        dataset_id,
                        dataset_version,
                        rec_id,
                        issue_type,
                        field_name,
                        message,
                        severity,
                        current_status,
                        now_str,
                        rev_decision,
                        rev_notes,
                    ),
                )

            issue_copy = dict(issue)
            issue_copy["issue_id"] = issue_id
            issue_copy["dataset_id"] = dataset_id
            issue_copy["dataset_version"] = dataset_version
            issue_copy["record_id"] = rec_id
            issue_copy["status"] = current_status
            issue_copy["reviewer_decision"] = rev_decision
            issue_copy["reviewer_notes"] = rev_notes
            saved_issues.append(issue_copy)

        conn.commit()
    finally:
        conn.close()

    return saved_issues


def update_expense_record(
    record_id: str,
    updates: Dict[str, Any],
    dataset_id: Optional[str] = None,
    dataset_version: Optional[int] = None,
    db_path: Optional[str] = None,
    **kwargs: Any,
) -> bool:
    """
    Safely update a stored expense record in expenses_v2.
    Allowed fields: expense_date, employee, description, merchant, category, amount,
                    receipt_status, receipt_path, location, payment_method, is_excluded.
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    field_map = {
        "date": "expense_date",
        "expense_date": "expense_date",
        "employee": "employee",
        "description": "description",
        "merchant": "merchant",
        "category": "category",
        "amount": "amount",
        "receipt_status": "receipt_status",
        "receipt_path": "receipt_path",
        "location": "location",
        "city": "location",
        "destination": "location",
        "payment_method": "payment_method",
        "is_excluded": "is_excluded",
    }

    set_clauses = []
    params: List[Any] = []

    for k, v in updates.items():
        k_clean = str(k).strip().lower()
        if k_clean in field_map:
            col = field_map[k_clean]
            set_clauses.append(f"{col} = ?")
            if col == "amount":
                params.append(_sanitize_amount(v, allow_none=True))
            elif col == "expense_date":
                params.append(_sanitize_date(v))
            elif col == "is_excluded":
                params.append(1 if v in (1, True, "1", "true") else 0)
            else:
                params.append(_sanitize_text(v))

    if not set_clauses:
        conn.close()
        return False

    set_clauses.append("updated_at = ?")
    now_str = datetime.now(timezone.utc).isoformat()
    params.append(now_str)

    where_clauses = ["record_id = ?"]
    params.append(record_id)

    if dataset_id:
        where_clauses.append("dataset_id = ?")
        params.append(dataset_id)
        if dataset_version is not None:
            where_clauses.append("dataset_version = ?")
            params.append(dataset_version)

    query = f"UPDATE expenses_v2 SET {', '.join(set_clauses)} WHERE {' AND '.join(where_clauses)}"

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
    **kwargs: Any,
) -> bool:
    """
    Update a validation finding's status:
    - 'resolved' (e.g. receipt provided / data corrected)
    - 'accepted_exception' (reviewer accepted with notes)
    - 'excluded' (transaction excluded from report calculations)
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()

    valid_statuses = {"resolved", "accepted_exception", "excluded", "unresolved"}
    status = decision.lower().strip()
    if status not in valid_statuses:
        status = "accepted_exception" if "accept" in status or "include" in status else "excluded"

    now_str = datetime.now(timezone.utc).isoformat()

    try:
        cursor.execute(
            """
            UPDATE validation_issues_v2
            SET status = ?, reviewer_decision = ?, reviewer_notes = ?, resolved_at = ?
            WHERE issue_id = ?
            """,
            (status, decision, notes, now_str, issue_id),
        )
        affected = cursor.rowcount > 0

        # If excluded, also mark is_excluded = 1 on associated expense record
        if status == "excluded":
            cursor.execute(
                "SELECT expense_record_id, dataset_id, dataset_version FROM validation_issues_v2 WHERE issue_id = ?",
                (issue_id,),
            )
            issue_row = cursor.fetchone()
            if issue_row:
                cursor.execute(
                    "UPDATE expenses_v2 SET is_excluded = 1, updated_at = ? WHERE record_id = ? AND dataset_id = ? AND dataset_version = ?",
                    (now_str, issue_row["expense_record_id"], issue_row["dataset_id"], issue_row["dataset_version"]),
                )

        conn.commit()
        return affected
    finally:
        conn.close()


def get_expense_by_record_id(
    record_id: str,
    dataset_id: Optional[str] = None,
    dataset_version: Optional[int] = None,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Retrieve a single stored expense record by record_id from expenses_v2.
    """
    init_memory_db(db_path)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    query = "SELECT * FROM expenses_v2 WHERE record_id = ?"
    params: List[Any] = [record_id]
    if dataset_id:
        query += " AND dataset_id = ?"
        params.append(dataset_id)
        if dataset_version is not None:
            query += " AND dataset_version = ?"
            params.append(dataset_version)
    query += " ORDER BY id DESC LIMIT 1"
    try:
        cursor.execute(query, params)
        r = cursor.fetchone()
        if not r:
            return None
        return {
            "record_id": r["record_id"],
            "dataset_id": r["dataset_id"],
            "dataset_version": r["dataset_version"],
            "date": r["expense_date"],
            "expense_date": r["expense_date"],
            "employee": r["employee"],
            "description": r["description"],
            "merchant": r["merchant"],
            "category": r["category"],
            "amount": float(r["amount"]) if r["amount"] is not None else None,
            "receipt_status": r["receipt_status"],
            "receipt_path": r["receipt_path"] or "",
            "location": r["location"],
            "payment_method": r["payment_method"],
            "is_excluded": r["is_excluded"],
            "source_file": r["source_file"],
        }
    finally:
        conn.close()


def apply_reviewer_decision(
    action: str,
    record_id: str,
    dataset_id: Optional[str] = None,
    dataset_version: Optional[int] = None,
    changes: Optional[Dict[str, Any]] = None,
    reason: str = "",
    db_path: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Apply a human reviewer compliance decision:
    - action == "correct": Updates record fields in expenses_v2, logs immutable audit event,
      revalidates the updated record, and marks resolved validation issues as 'resolved'.
    - action == "exclude": Marks record as is_excluded = 1 in expenses_v2, logs audit event,
      and marks associated validation issues as 'excluded'.
    - action == "accept_exception": Marks associated validation issues as 'accepted_exception'
      with manager reason/notes, and logs audit event.
    """
    init_memory_db(db_path)
    action_clean = str(action).lower().strip()
    now_str = datetime.now(timezone.utc).isoformat()

    if dataset_id is None:
        active = get_active_dataset(db_path)
        if active:
            dataset_id = active["dataset_id"]
            if dataset_version is None:
                dataset_version = active.get("version", 1)
        else:
            dataset_id = LEGACY_DATASET_ID
            if dataset_version is None:
                dataset_version = 1

    if action_clean in ("correct", "correction", "edit", "update"):
        updates = changes or {}
        success = update_expense_record(
            record_id=record_id,
            updates=updates,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            db_path=db_path,
        )

        updated_rec = get_expense_by_record_id(
            record_id=record_id,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            db_path=db_path,
        )

        from tools.validation_tools import revalidate_single_expense
        remaining_issues = revalidate_single_expense(updated_rec) if updated_rec else []

        conn = get_connection(db_path)
        cursor = conn.cursor()
        try:
            if not remaining_issues:
                cursor.execute(
                    """
                    UPDATE validation_issues_v2
                    SET status = 'resolved', reviewer_decision = 'correct',
                        reviewer_notes = ?, resolved_at = ?
                    WHERE expense_record_id = ? AND dataset_id = ? AND status = 'unresolved'
                    """,
                    (reason or "Corrected by reviewer", now_str, record_id, dataset_id),
                )
            else:
                remaining_types = [iss["issue_type"] for iss in remaining_issues]
                placeholders = ",".join("?" for _ in remaining_types)
                cursor.execute(
                    f"""
                    UPDATE validation_issues_v2
                    SET status = 'resolved', reviewer_decision = 'correct',
                        reviewer_notes = ?, resolved_at = ?
                    WHERE expense_record_id = ? AND dataset_id = ? AND status = 'unresolved'
                      AND issue_type NOT IN ({placeholders})
                    """,
                    [reason or "Partially corrected", now_str, record_id, dataset_id] + remaining_types,
                )
            conn.commit()
        finally:
            conn.close()

        event_id = save_audit_event(
            dataset_id=dataset_id,
            event_type="reviewer_correction",
            entity_type="expense",
            entity_id=record_id,
            details={"changes": updates, "reason": reason, "remaining_issues": len(remaining_issues)},
            db_path=db_path,
        )

        return {
            "action": "correct",
            "success": success,
            "record_id": record_id,
            "updated_record": updated_rec,
            "remaining_issues": remaining_issues,
            "audit_event_id": event_id,
        }

    elif action_clean in ("exclude", "exclude_single", "excluded"):
        conn = get_connection(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE expenses_v2
                SET is_excluded = 1, updated_at = ?
                WHERE record_id = ? AND dataset_id = ?
                """,
                (now_str, record_id, dataset_id),
            )
            cursor.execute(
                """
                UPDATE validation_issues_v2
                SET status = 'excluded', reviewer_decision = 'exclude',
                    reviewer_notes = ?, resolved_at = ?
                WHERE expense_record_id = ? AND dataset_id = ?
                """,
                (reason or "Excluded by reviewer", now_str, record_id, dataset_id),
            )
            conn.commit()
        finally:
            conn.close()

        event_id = save_audit_event(
            dataset_id=dataset_id,
            event_type="reviewer_exclusion",
            entity_type="expense",
            entity_id=record_id,
            details={"reason": reason or "Excluded by reviewer"},
            db_path=db_path,
        )

        return {
            "action": "exclude",
            "success": True,
            "record_id": record_id,
            "status": "excluded",
            "audit_event_id": event_id,
        }

    elif action_clean in ("accept_exception", "include", "accept_exceptions", "accepted_exception", "resolved"):
        conn = get_connection(db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE validation_issues_v2
                SET status = 'accepted_exception', reviewer_decision = 'accept_exception',
                    reviewer_notes = ?, resolved_at = ?
                WHERE expense_record_id = ? AND dataset_id = ?
                """,
                (reason or "Authorized managerial exception", now_str, record_id, dataset_id),
            )
            conn.commit()
        finally:
            conn.close()

        event_id = save_audit_event(
            dataset_id=dataset_id,
            event_type="reviewer_exception_accepted",
            entity_type="expense",
            entity_id=record_id,
            details={"reason": reason or "Authorized managerial exception"},
            db_path=db_path,
        )

        return {
            "action": "accept_exception",
            "success": True,
            "record_id": record_id,
            "status": "accepted_exception",
            "audit_event_id": event_id,
        }

    else:
        raise ValueError(f"Unknown reviewer action: {action}. Must be 'correct', 'exclude', or 'accept_exception'.")


def get_unresolved_issues(
    dataset_id: Optional[str] = None,
    dataset_version: Optional[int] = None,
    employee: Optional[str] = None,
    db_path: Optional[str] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Retrieve all open/unresolved issues from memory scoped to dataset."""
    init_memory_db(db_path)

    if dataset_id is None:
        active = get_active_dataset(db_path)
        if active:
            dataset_id = active["dataset_id"]
            if dataset_version is None:
                dataset_version = active.get("version", 1)

    conn = get_connection(db_path)
    cursor = conn.cursor()

    query = """
        SELECT vi.*, e.employee, e.expense_date, e.description, e.merchant, e.amount, e.receipt_status, e.location
        FROM validation_issues_v2 vi
        JOIN expenses_v2 e ON vi.expense_record_id = e.record_id AND vi.dataset_id = e.dataset_id AND vi.dataset_version = e.dataset_version
        WHERE vi.status = 'unresolved'
    """
    params: List[Any] = []

    if dataset_id:
        query += " AND vi.dataset_id = ?"
        params.append(dataset_id)
        if dataset_version is not None:
            query += " AND vi.dataset_version = ?"
            params.append(dataset_version)

    if employee and employee.strip():
        query += " AND LOWER(e.employee) LIKE ?"
        params.append(f"%{employee.strip().lower()}%")

    query += " ORDER BY vi.id DESC"

    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["amount"] = float(r["amount"]) if r["amount"] is not None else None
            results.append(d)
        return results
    finally:
        conn.close()


# =====================================================================
# Report Runs & History Persistence
# =====================================================================

def save_report_run(
    report_data: Dict[str, Any],
    dataset_id: Optional[str] = None,
    dataset_version: Optional[int] = None,
    db_path: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """
    Persist an executed report run in SQLite memory scoped to dataset_id and version.
    Returns stable report_id.
    """
    init_memory_db(db_path)

    report_id = report_data.get("report_id") or f"REP-{uuid.uuid4().hex[:10]}"
    run_id = report_data.get("run_id") or f"RUN-{report_id}"

    dataset_id = dataset_id or report_data.get("dataset_id")
    if dataset_id is None:
        active = get_active_dataset(db_path)
        if active:
            dataset_id = active["dataset_id"]
            if dataset_version is None:
                dataset_version = report_data.get("dataset_version") or active.get("version", 1)
        else:
            dataset_id = LEGACY_DATASET_ID
            if dataset_version is None:
                dataset_version = report_data.get("dataset_version", 1)

    now_str = datetime.now(timezone.utc).isoformat()
    conn = get_connection(db_path)
    cursor = conn.cursor()
    dataset_version = _ensure_dataset_registered(cursor, dataset_id, dataset_version, 0)

    try:
        cursor.execute(
            """
            INSERT INTO report_runs_v2 (
                run_id, report_id, dataset_id, dataset_version,
                user_request, filters_json, transaction_ids_json,
                transaction_count, grand_total, validation_status,
                report_file_path, human_review_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                report_id,
                dataset_id,
                dataset_version,
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


def get_report_history(
    dataset_id: Optional[str] = None,
    dataset_version: Optional[int] = None,
    limit: int = 50,
    db_path: Optional[str] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """
    Retrieve historical report runs from memory scoped to dataset.
    """
    init_memory_db(db_path)

    if dataset_id is None:
        active = get_active_dataset(db_path)
        if active:
            dataset_id = active["dataset_id"]

    conn = get_connection(db_path)
    cursor = conn.cursor()

    query = "SELECT * FROM report_runs_v2 WHERE 1=1"
    params: List[Any] = []

    if dataset_id:
        query += " AND dataset_id = ?"
        params.append(dataset_id)
        if dataset_version is not None:
            query += " AND dataset_version = ?"
            params.append(dataset_version)

    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)

    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        results = []
        for r in rows:
            results.append({
                "run_id": r["run_id"],
                "report_id": r["report_id"],
                "dataset_id": r["dataset_id"],
                "dataset_version": r["dataset_version"],
                "user_request": r["user_request"],
                "filters": json.loads(r["filters_json"] or "{}"),
                "transaction_ids": json.loads(r["transaction_ids_json"] or "[]"),
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


# =====================================================================
# Memory Statistics
# =====================================================================

def get_memory_stats(
    dataset_id: Optional[str] = None,
    db_path: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Retrieve summary counts from persistent memory scoped to dataset.
    """
    init_memory_db(db_path)

    if dataset_id is None:
        active = get_active_dataset(db_path)
        if active:
            dataset_id = active["dataset_id"]

    conn = get_connection(db_path)
    cursor = conn.cursor()

    try:
        if dataset_id:
            cursor.execute("SELECT version FROM datasets WHERE dataset_id = ?", (dataset_id,))
            ds_row = cursor.fetchone()
            curr_ver = ds_row["version"] if ds_row else 1

            cursor.execute(
                "SELECT COUNT(*) AS total FROM expenses_v2 WHERE dataset_id = ? AND dataset_version = ? AND is_excluded = 0",
                (dataset_id, curr_ver),
            )
            exp_count = cursor.fetchone()["total"]

            cursor.execute(
                "SELECT COUNT(DISTINCT employee) AS emps FROM expenses_v2 WHERE dataset_id = ? AND dataset_version = ?",
                (dataset_id, curr_ver),
            )
            emp_count = cursor.fetchone()["emps"]

            cursor.execute(
                "SELECT COUNT(*) AS unresolved FROM validation_issues_v2 WHERE dataset_id = ? AND dataset_version = ? AND status = 'unresolved'",
                (dataset_id, curr_ver),
            )
            unresolved_issues = cursor.fetchone()["unresolved"]

            cursor.execute(
                "SELECT COUNT(*) AS total_reports FROM report_runs_v2 WHERE dataset_id = ?",
                (dataset_id,),
            )
            report_count = cursor.fetchone()["total_reports"]
        else:
            cursor.execute("SELECT COUNT(*) AS total FROM expenses_v2 WHERE is_excluded = 0")
            exp_count = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(DISTINCT employee) AS emps FROM expenses_v2")
            emp_count = cursor.fetchone()["emps"]

            cursor.execute("SELECT COUNT(*) AS unresolved FROM validation_issues_v2 WHERE status = 'unresolved'")
            unresolved_issues = cursor.fetchone()["unresolved"]

            cursor.execute("SELECT COUNT(*) AS total_reports FROM report_runs_v2")
            report_count = cursor.fetchone()["total_reports"]

        return {
            "total_expenses": exp_count,
            "unique_employees": emp_count,
            "unresolved_issues": unresolved_issues,
            "total_reports": report_count,
        }
    finally:
        conn.close()
