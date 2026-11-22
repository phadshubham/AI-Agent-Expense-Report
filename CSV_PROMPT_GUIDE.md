# 📋 CSV Data & Prompt Guide for AI Expense Report Agent

This comprehensive guide details all available CSV expense datasets in the workspace, their exact date distributions, employee coverage, column schemas, and a **Prompt Cookbook** demonstrating how to formulate natural language requests for every scenario.

---

## 🌟 Core Engine Capabilities

- **Zero Hardcoding**: Employees, merchants, categories, and locations are discovered dynamically from whatever dataset is currently active.
- **True All-Date Support**: Prompts like `"Generate all expenses report for Ravi Kumar"` or `"All travel expenses"` do **not** force a default timeframe like "last month" — they query across all transactions in the active dataset.
- **Typo Tolerance**: Automatically resolves common phonetic spelling mistakes in month names (e.g. `"augest"` → August, `"aprl"` → April) and capitalization variances.
- **Single-Person Reports**: When you specify an employee (e.g. `"for Priya Sharma"`), the agent generates a focused PDF report tailored exclusively to that individual.
- **Consolidated Multi-Person Reports**: When you ask for an entire period or team (e.g. `"Generate August 2026 expense report"`), the agent generates **ONE consolidated PDF** featuring:
  1. An **Executive Summary Table** with all employees, transaction counts, subtotals, and missing receipt counts.
  2. **Individual dedicated sections for each employee**, including their transaction tables, category breakdowns, and receipt statuses.
- **Intelligent Zero-Match Diagnostics**: If a prompt does not match records (e.g. requesting a future month or an employee not in the active dataset), the agent provides a clear diagnostic notice explaining why (e.g. showing the actual date range of the dataset).
- **Persistent Compliance Memory**: Transactions excluded (`❌ Exclude`) or authorized (`✅ Authorize Exception`) in the Compliance Audit tab or during review are remembered in SQLite memory; subsequent workflow runs do not pause redundantly.

---

## 🏢 1. Master Company Dataset: 170 Records Across 5 Months & 5 Employees

- **Primary Path:** [`data/expenses.csv`](data/expenses.csv)
- **Sample Mirror:** [`data/sample_csvs/5_Company_Expenses_Apr_to_Aug2026.csv`](data/sample_csvs/5_Company_Expenses_Apr_to_Aug2026.csv)
- **Total Records:** **170 transactions**
- **Date Range:** `2026-04-01` to `2026-08-31`
- **Columns:** `date`, `description`, `merchant`, `amount`, `category`, `receipt_status`, `employee`, `payment_method`

### 📊 Monthly Distribution
| Month | Date Range | Transactions |
| :--- | :--- | :--- |
| **April 2026** | `2026-04-01` to `2026-04-30` | **26** |
| **May 2026** | `2026-05-01` to `2026-05-31` | **32** |
| **June 2026** | `2026-06-01` to `2026-06-30` | **30** |
| **July 2026** | `2026-07-01` to `2026-07-31` | **38** |
| **August 2026** | `2026-08-01` to `2026-08-31` | **44** |

### 👥 Employee Breakdown
| Employee Name | Role | Total Transactions |
| :--- | :--- | :--- |
| **Ravi Kumar** | Senior Consultant | **46** |
| **Priya Sharma** | Product Manager | **38** |
| **Amit Patel** | Sales Lead | **34** |
| **Sneha Reddy** | Software Architect | **28** |
| **Vikram Singh** | Operations Specialist | **24** |

---

## 📁 2. Additional Scenario Datasets

### A. Multi-Month Focused Dataset (19 Records)
- **File:** [`data/sample_csvs/4_Multi_Month_Expenses_Jun_Jul_Aug2026.csv`](data/sample_csvs/4_Multi_Month_Expenses_Jun_Jul_Aug2026.csv)
- **Total Rows:** 19
- **Date Range:** `2026-06-10` to `2026-08-12`
- **Employee:** Ravi Kumar
- **Key Use Case:** Testing multi-month queries and open-ended employee queries.

### B. Delhi Travel Dataset (8 Records)
- **File:** [`data/sample_csvs/1_Delhi_Travel_Aug2026.csv`](data/sample_csvs/1_Delhi_Travel_Aug2026.csv)
- **Total Rows:** 8
- **Date Range:** `2026-08-05` to `2026-08-12`
- **Employee:** Ravi Kumar
- **Key Use Case:** Testing single trip reporting and missing receipt compliance checks.

### C. Mumbai Client Visit Dataset (6 Records)
- **File:** [`data/sample_csvs/2_Mumbai_Client_Visit_Jul2026.csv`](data/sample_csvs/2_Mumbai_Client_Visit_Jul2026.csv)
- **Total Rows:** 6
- **Date Range:** `2026-07-15` to `2026-07-17`
- **Employee:** Ravi Kumar
- **Key Use Case:** Short client trip validation.

### D. Tech Conference Bangalore (6 Records)
- **File:** [`data/sample_csvs/3_Tech_Conference_Bangalore_Aug2026.csv`](data/sample_csvs/3_Tech_Conference_Bangalore_Aug2026.csv)
- **Total Rows:** 6
- **Date Range:** `2026-08-25` to `2026-08-27`
- **Employee:** Ravi Kumar
- **Key Use Case:** High-value registration fees and corporate card verification.

---

## 💡 Prompt Cookbook: Recommended Prompts to Try

### 1. Open-Ended All-Date Queries (No Date Restriction)
These prompts query across the entire dataset without defaulting to a single month:
- > `"Generate all expenses report for Ravi Kumar"`
- > `"All expenses for Priya Sharma"`
- > `"Generate all travel expenses report"`
- > `"All expenses report for Amit Patel"`

### 2. Specific Month Queries
- **August 2026:**
  > `"Travel expenses for August 2026"`  
  > *(Generates a consolidated report for all 5 employees in August)*
- **July 2026:**
  > `"Generate travel expense report for July 2026"`
- **May 2026:**
  > `"All travel expenses for May 2026"`
- **April 2026:**
  > `"April 2026 expenses report"`

### 3. Employee + Timeframe Combinations (Typo-Tolerant)
- **Priya Sharma with intentional typo:**
  > `"Generate augest report for Priya Sharma"`  
  *(Tolerates spelling typos like `"augest"` and matches Priya Sharma)*
- **Amit Patel in August:**
  > `"August 2026 expenses for Amit Patel"`
- **Vikram Singh in May:**
  > `"May 2026 travel report for Vikram Singh"`
- **Sneha Reddy in July:**
  > `"Generate July report for Sneha Reddy"`
- **Ravi Kumar in April:**
  > `"April travel expenses for Ravi Kumar"`

### 4. Custom Date Range Queries
- > `"Generate travel expense report from April 1 2026 to August 31 2026"`
- > `"Expenses between 2026-06-01 and 2026-07-31"`
- > `"Travel report from July 1 2026 to August 15 2026"`

### 5. Category-Specific Queries
- > `"Flight expenses for August 2026"`
- > `"Meal and food expenses for Priya Sharma"`
- > `"Hotel accommodation expenses for July 2026"`
- > `"Cab and transport expenses for Ravi Kumar"`

---

## 🛡️ Interactive Data Editing & Compliance Scenarios

### In-Place Table Editing
1. In **Tab 1 (Executive Workspace & Execution)**, use the interactive table editor to edit values directly (e.g. updating an amount or correcting a receipt status from `Missing` to `Verified`).
2. Click **"💾 Save Table as Version v2"** to snapshot the edited dataset into SQLite memory.
3. Run your prompt: the agent automatically evaluates against your newly updated version!

### Handling Flagged Compliance Issues
1. When a transaction has a missing receipt or invalid amount, the Validation Agent will flag it.
2. In the Human-in-the-Loop console, you can:
   - **Input Missing Value**: Provide the exact financial amount or date, then revalidate.
   - **Exclude Item**: Omit the transaction from counting and grand totals.
   - **Authorize Managerial Exception**: Include the item with documented compliance notes.
3. Alternatively, visit **Tab 4 (Compliance & Audit Issue Management)** and use **Auditor Direct Resolution** to pre-authorize or exclude items before running the workflow.
