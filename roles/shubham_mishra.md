# Role Dossier: Shubham Mishra (ADT23SOCB1110)
## Database Architect & Cryptographic Memory Specialist

---

### 1. Executive Summary & Core Identity
As the **Database Architect & Cryptographic Memory Specialist**, you own the **data foundation**, **two-tier SQLite architecture**, **cryptographic dataset isolation**, and **content-signature deduplication engine**. 

If the teacher asks: *"How do you store data, prevent duplicates, and ensure different CSVs don't mix up?"* or *"How did you fix the 340-row duplication bug?"* — **You are the one who answers.**

---

### 2. Modules & Core Architecture Owned

#### A. Two-Tier Isolated Storage Architecture
You architected the structural decoupling between business data and workflow checkpoints:
1. **Tier 1: Business Domain Memory (`data/expense_memory.db`)**:
   * Houses permanent financial entities: `datasets`, `expenses_v2`, `validation_issues_v2`, `report_runs_v2`, `audit_events`, and `import_batches`.
   * Enforces referential integrity with foreign keys and index optimization on `dataset_id`.
2. **Tier 2: Workflow State Checkpointer (`.checkpoints/agent_state.db`)**:
   * Managed by LangGraph `SqliteSaver`.
   * Stores binary execution thread state, graph checkpoints, and resume triggers for Human-in-the-Loop workflows.

#### B. Cryptographic SHA-256 Dataset Identity & Isolation
* When a user uploads a CSV, you compute a **SHA-256 file hash** (`file_hash = sha256(file_bytes)`).
* You register an immutable `dataset_id` (e.g., `DS-35e25222fe`) in the `datasets` registry table.
* **Database Query Scoping**: Every single query (`SELECT`, `INSERT`, `UPDATE`, `DELETE`) in `tools/memory_tools.py` requires an explicit `dataset_id`. 
* **Zero Contamination**: If the user switches from Dataset A to Dataset B, Dataset A's records, validation issues, prompt history, and report snapshots remain strictly quarantined in SQLite.

#### C. The Content-Signature Deduplication Engine (The 340-Row Bug Fix)
* **Root Cause of the Bug**: During initial testing, re-running Agent 1 on a 170-row dataset generated 170 duplicates because record IDs were generated from transient session strings like `source_name="active_session"`.
* **Your Solution**: You built a **deterministic cryptographic content pool**:
  $$\text{ContentHash} = \text{SHA-256}(\text{date} \parallel \text{employee} \parallel \text{description} \parallel \text{merchant} \parallel \text{amount})$$
* Before inserting records, your engine loads all existing content signatures for that `dataset_id`. If a record's signature matches an existing entry, it retains the existing canonical `record_id` and does not insert a duplicate row.
* This preserved the pristine **170-row count and exact ₹609,550.00 total spend** across arbitrary runs.

#### D. Audit Trail & Reviewer Memory Persistence
* Built `audit_events` and `validation_issues_v2` tables to store reviewer actions (`accept_exception`, `exclude`, `correct`).
* When Agent 2 validates records, it queries `validation_issues_v2` to check whether an auditor previously approved an exception for that record ID.

---

### 3. Critical Code You Authored & Must Walk Through

#### A. Production Database Schema (`tools/memory_tools.py`)
```python
def init_db(db_path: str = DB_PATH):
    """
    Initializes the production SQLite schema with cryptographic dataset scoping.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()
        
        # 1. Dataset Registry
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS datasets (
                dataset_id TEXT PRIMARY KEY,
                dataset_name TEXT NOT NULL,
                source_filename TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            );
        """)
        
        # 2. Scoped Expenses Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses_v2 (
                record_id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                date TEXT NOT NULL,
                employee TEXT NOT NULL,
                description TEXT,
                merchant TEXT,
                category TEXT,
                amount REAL NOT NULL,
                receipt_status TEXT DEFAULT 'Available',
                location TEXT,
                import_hash TEXT NOT NULL,
                FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id) ON DELETE CASCADE
            );
        """)
        
        # 3. Validation Issues & Audit Events
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS validation_issues_v2 (
                issue_id TEXT PRIMARY KEY,
                dataset_id TEXT NOT NULL,
                expense_record_id TEXT NOT NULL,
                issue_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'unresolved',
                reviewer_action TEXT,
                reviewer_note TEXT,
                resolved_at TIMESTAMP
            );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_exp_dataset ON expenses_v2(dataset_id);")
        conn.commit()
```

#### B. Content-Signature Deduplication Engine (`tools/memory_tools.py`)
```python
def save_expenses(expenses: list, source_name: str, dataset_id: str, db_path: str = DB_PATH) -> dict:
    """
    Saves expense records idempotently using cryptographic content-hash pooling.
    Prevents duplicate record insertion on repeated workflow runs.
    """
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        
        # Fetch existing content signatures for this dataset
        cursor.execute(
            "SELECT record_id, date, employee, description, merchant, amount FROM expenses_v2 WHERE dataset_id = ?",
            (dataset_id,)
        )
        existing_pool = {}
        for r_id, dt, emp, desc, merch, amt in cursor.fetchall():
            sig = f"{dt}|{str(emp).strip().lower()}|{str(desc).strip().lower()}|{str(merch).strip().lower()}|{float(amt):.2f}"
            existing_pool[sig] = r_id
            
        inserted = 0
        preserved = 0
        output_records = []
        
        for item in expenses:
            dt = str(item.get("date", "")).strip()
            emp = str(item.get("employee", "")).strip().lower()
            desc = str(item.get("description", "")).strip().lower()
            merch = str(item.get("merchant", "")).strip().lower()
            amt = float(item.get("amount", 0.0) or 0.0)
            
            sig = f"{dt}|{emp}|{desc}|{merch}|{amt:.2f}"
            
            if sig in existing_pool:
                # Existing record: reuse canonical ID without re-inserting
                canonical_id = existing_pool[sig]
                record_copy = dict(item)
                record_copy["record_id"] = canonical_id
                output_records.append(record_copy)
                preserved += 1
            else:
                # Genuine new record: compute deterministic hash
                new_id = f"EXP-{hashlib.sha256(f'{dataset_id}_{sig}'.encode()).hexdigest()[:12]}"
                cursor.execute("""
                    INSERT INTO expenses_v2 (record_id, dataset_id, date, employee, description, merchant, category, amount, receipt_status, location, import_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (new_id, dataset_id, item["date"], item["employee"], item["description"], item["merchant"], item["category"], amt, item.get("receipt_status", "Available"), item.get("location"), "hash_v2"))
                existing_pool[sig] = new_id
                inserted += 1
                record_copy = dict(item)
                record_copy["record_id"] = new_id
                output_records.append(record_copy)
                
        conn.commit()
        return {"inserted": inserted, "preserved": preserved, "records": output_records}
```

---

### 4. Likely Teacher / Viva Questions & Model Answers

* **Q1: "Explain how you solved the 340-row duplication bug."**
  * **Your Answer**: *"Originally, when the CSV was loaded, records were given one hash. When Agent 1 executed, it received records without `record_id` and called `save_expenses` using `source_name='active_session'`. This generated 170 new hashes and doubled the database to 340 rows. I permanently fixed this by introducing a **Cryptographic Content-Signature Pool**. Before inserting, my code queries all existing tuples `(date, employee, description, merchant, amount)` for that `dataset_id`. If a record matches an existing content signature, it reuses the canonical `record_id` instead of duplicating it."*

* **Q2: "Why do you have two SQLite databases instead of keeping everything in one?"**
  * **Your Answer**: *"Because of architectural decoupling. `expense_memory.db` stores business domain entities (datasets, transactions, audit logs). `.checkpoints/agent_state.db` stores low-level execution thread state and serialized LangGraph binary blobs. Keeping them separate ensures that if the agent state needs to be checkpointed or reset, the permanent financial audit logs and raw expense data remain completely untouched and clean."*

* **Q3: "How do you guarantee that uploading a new CSV doesn't show old data?"**
  * **Your Answer**: *"Every dataset is assigned an isolated SHA-256 `dataset_id`. All retrieval methods in `tools/memory_tools.py` (`get_expenses`, `get_validation_issues`, `get_dataset_runs`) require an explicit `dataset_id = ?` parameter in the SQL `WHERE` clause. There is zero database-level leakage between datasets."*
