# 📋 CSV Data & Prompt Guide for AI Expense Report Agent

This guide lists all available CSV expense datasets in the workspace, along with their exact date ranges, employee distributions, and recommended prompts to use in the application.

> [!NOTE]  
> **Current Date Baseline:** `2026-09-01` (September 1, 2026).  
> All dataset dates occur in the 5 consecutive months prior to September 2026 (April to August 2026).

---

## 🌟 Dynamic Employee Handling & Multi-Person PDF Generation

- **Zero Hardcoding**: Employees are detected **dynamically** from your prompt or directly from whatever dataset is loaded (no static lists).
- **Single-Person Request**: When you specify an employee (e.g. `"for Priya Sharma"`), the agent generates a PDF tailored exclusively to that person.
- **Multi-Person / Period Request**: When you ask for a period without specifying one person (e.g. `"Generate August report"`), the agent automatically gathers all employees who have expenses, calculates individual subtotals, and generates **ONE consolidated PDF** containing:
  1. An **Executive Summary Table** showing all employees, transaction counts, subtotals, and missing receipts.
  2. **Individual dedicated sections for each person**, complete with their own transaction tables, category breakdowns, and receipt notes.

---

## 🏢 1. Master Company Dataset: 170 Records Across 5 Months & 5 Employees

- **Sample CSV:** [`data/sample_csvs/5_Company_Expenses_Apr_to_Aug2026.csv`](file:///c:/Users/Space/OneDrive/Documents/AI%20Agent%20Expense%20report/data/sample_csvs/5_Company_Expenses_Apr_to_Aug2026.csv)
- **Also Default DB:** [`data/expenses.csv`](file:///c:/Users/Space/OneDrive/Documents/AI%20Agent%20Expense%20report/data/expenses.csv)
- **Total Records:** **170 transactions** (exceeds the 150 minimum requirement)

### 📊 Uneven Distribution Across 5 Months (Before September 2026):
| Month | Dates | Transactions |
| :--- | :--- | :--- |
| **April 2026** | `2026-04-01` to `2026-04-30` | **26** |
| **May 2026** | `2026-05-01` to `2026-05-31` | **32** |
| **June 2026** | `2026-06-01` to `2026-06-30` | **30** |
| **July 2026** | `2026-07-01` to `2026-07-31` | **38** |
| **August 2026** | `2026-08-01` to `2026-08-31` | **44** |

### 👥 Uneven Distribution Across 5 Employees:
| Employee Name | Role | Total Transactions |
| :--- | :--- | :--- |
| **Ravi Kumar** | Senior Consultant | **46** |
| **Priya Sharma** | Product Manager | **38** |
| **Amit Patel** | Sales Lead | **34** |
| **Sneha Reddy** | Software Architect | **28** |
| **Vikram Singh** | Operations Specialist | **24** |

---

### 💬 Prompts to Try:

#### 🟢 Multi-Person Consolidated Reports (One PDF with all employees):
- > `"Generate travel expense report for last month"`
- > `"Generate expense report for August 2026"`
- > `"Generate travel expense report for July 2026"`
- > `"Generate travel expense report from April 1 2026 to August 31 2026"`

#### 🔵 Specific Person Reports (Dedicated PDF for that person only):
- **Priya Sharma in August:**
  > `"Generate augest report for Priya Sharma"`  
  *(Tolerates spelling typos like `"augest"`)*
- **Amit Patel in August:**
  > `"Generate august report for Amit Patel"`
- **Vikram Singh in May:**
  > `"Generate May 2026 report for Vikram Singh"`
- **Sneha Reddy in July:**
  > `"Generate July report for Sneha Reddy"`
- **Ravi Kumar in April:**
  > `"Generate April 2026 travel expense report for Ravi Kumar"`

---

## 📁 2. Other Sample Datasets

- [`4_Multi_Month_Expenses_Jun_Jul_Aug2026.csv`](file:///c:/Users/Space/OneDrive/Documents/AI%20Agent%20Expense%20report/data/sample_csvs/4_Multi_Month_Expenses_Jun_Jul_Aug2026.csv) (19 records across June, July, August)
- [`1_Delhi_Travel_Aug2026.csv`](file:///c:/Users/Space/OneDrive/Documents/AI%20Agent%20Expense%20report/data/sample_csvs/1_Delhi_Travel_Aug2026.csv) (August 2026 trip)
- [`2_Mumbai_Client_Visit_Jul2026.csv`](file:///c:/Users/Space/OneDrive/Documents/AI%20Agent%20Expense%20report/data/sample_csvs/2_Mumbai_Client_Visit_Jul2026.csv) (July 2026 trip)
- [`3_Tech_Conference_Bangalore_Aug2026.csv`](file:///c:/Users/Space/OneDrive/Documents/AI%20Agent%20Expense%20report/data/sample_csvs/3_Tech_Conference_Bangalore_Aug2026.csv) (August 2026 conference)
