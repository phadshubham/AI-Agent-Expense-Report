"""
Generate publication-grade Block Diagram and Workflow Flowchart for the project report.
"""
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches

os.makedirs("report_assets", exist_ok=True)

# ---------------------------------------------------------------------------
# 1. BLOCK DIAGRAM
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 5.5), dpi=300)
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")

# Background styling
fig.patch.set_facecolor("#ffffff")

# Titles
ax.text(50, 96, "AI-Powered Expense Report Management System", ha="center", va="center", fontsize=13, fontweight="bold", color="#0f172a")
ax.text(50, 92, "Multi-Agent System Architecture & Component Block Diagram", ha="center", va="center", fontsize=9, color="#64748b")

# Helper for rounded box
def add_box(x, y, w, h, bg="#ffffff", border="#cbd5e1", lw=1.2, ls="-", round_pad=0.3):
    p = patches.FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad={round_pad}", facecolor=bg, edgecolor=border, linewidth=lw, linestyle=ls)
    ax.add_patch(p)
    return p

# Outer boundary: User Interaction Layer
add_box(3, 56, 24, 30, bg="#eff6ff", border="#3b82f6", lw=1.5, ls="--")
ax.text(15, 83, "User Interaction Layer", ha="center", va="center", fontsize=9, fontweight="bold", color="#1d4ed8")
add_box(5, 70, 20, 9, bg="#ffffff", border="#cbd5e1", lw=1)
ax.text(15, 74.5, "Streamlit FinTech UI\n(Table Editor & Control)", ha="center", va="center", fontsize=7.5, color="#0f172a")
add_box(5, 59, 20, 8, bg="#ffffff", border="#cbd5e1", lw=1)
ax.text(15, 63, "HITL Review Console\n(Managerial Overrides)", ha="center", va="center", fontsize=7.5, color="#0f172a")

# Middle boundary: LangGraph Multi-Agent Orchestrator
add_box(31, 36, 38, 50, bg="#f8fafc", border="#1a237e", lw=1.8)
ax.text(50, 83, "LangGraph Multi-Agent Orchestration Layer", ha="center", va="center", fontsize=9.5, fontweight="bold", color="#1a237e")

# Agent 1
add_box(34, 68, 32, 11, bg="#ffffff", border="#2563eb", lw=1.2)
ax.text(50, 75.5, "Agent 1: Expense Analysis Agent", ha="center", va="center", fontsize=8.5, fontweight="bold", color="#1e3a8a")
ax.text(50, 71.5, "• NLU Intent Parser (Qwen 3 / Regex)\n• Dynamic Entity Matcher & Deterministic Filters", ha="center", va="center", fontsize=6.8, color="#475569")

# Agent 2
add_box(34, 53, 32, 12, bg="#ffffff", border="#d97706", lw=1.2)
ax.text(50, 61.5, "Agent 2: Compliance & Validation Agent", ha="center", va="center", fontsize=8.5, fontweight="bold", color="#92400e")
ax.text(50, 56.5, "• Policy Audit Engine & Receipt Verifier\n• Missing Values & Null-Resilience Handler", ha="center", va="center", fontsize=6.8, color="#475569")

# Agent 3
add_box(34, 38, 32, 12, bg="#ffffff", border="#059669", lw=1.2)
ax.text(50, 46.5, "Agent 3: Report Generation Agent", ha="center", va="center", fontsize=8.5, fontweight="bold", color="#065f46")
ax.text(50, 41.5, "• Mathematical Integrity Guard (Pandas Math)\n• Vector PDF Builder & SQLite Archiver", ha="center", va="center", fontsize=6.8, color="#475569")

# Right boundary: Output & Dispatch
add_box(73, 46, 24, 40, bg="#ecfdf5", border="#059669", lw=1.5, ls="--")
ax.text(85, 83, "Output & Dispatch Layer", ha="center", va="center", fontsize=9, fontweight="bold", color="#065f46")
add_box(75, 70, 20, 9, bg="#ffffff", border="#a7f3d0", lw=1)
ax.text(85, 74.5, "ReportLab Vector PDF\n(Official Audit Badges)", ha="center", va="center", fontsize=7.5, color="#0f172a")
add_box(75, 58, 20, 9, bg="#ffffff", border="#a7f3d0", lw=1)
ax.text(85, 62.5, "AI Email Dispatch\n(Ollama Qwen 3 + Resend)", ha="center", va="center", fontsize=7.5, color="#0f172a")
add_box(75, 48, 20, 7, bg="#ffffff", border="#a7f3d0", lw=1)
ax.text(85, 51.5, "Audit History Repository\n(Reproducible Runs)", ha="center", va="center", fontsize=7, color="#0f172a")

# Bottom boundary: Two-Tier Storage Architecture
add_box(5, 5, 90, 26, bg="#ffffff", border="#475569", lw=1.5)
ax.text(50, 27.5, "Two-Tier Isolated Storage Architecture", ha="center", va="center", fontsize=9.5, fontweight="bold", color="#0f172a")

add_box(8, 8, 40, 16, bg="#f8fafc", border="#1a237e", lw=1.2)
ax.text(28, 20.5, "Tier 1: Business Memory DB", ha="center", va="center", fontsize=8.5, fontweight="bold", color="#1a237e")
ax.text(28, 14, "data/expense_memory.db (SQLite)\n• datasets, expenses_v2, validation_issues_v2\n• report_runs_v2, audit_events, import_batches", ha="center", va="center", fontsize=7, color="#334155")

add_box(52, 8, 40, 16, bg="#eff6ff", border="#2563eb", lw=1.2)
ax.text(72, 20.5, "Tier 2: Workflow Checkpointer DB", ha="center", va="center", fontsize=8.5, fontweight="bold", color="#2563eb")
ax.text(72, 14, ".checkpoints/agent_state.db (SQLite)\n• LangGraph SqliteSaver Thread Checkpoints\n• Serialized Execution Graphs & Resume States", ha="center", va="center", fontsize=7, color="#334155")

# Arrows
arrow_kw = dict(arrowstyle="->", color="#1e3a8a", lw=1.5)
ax.annotate("", xy=(34, 73.5), xytext=(25, 73.5), arrowprops=arrow_kw)
ax.annotate("", xy=(34, 59), xytext=(25, 63), arrowprops=arrow_kw)
ax.annotate("", xy=(25, 60), xytext=(34, 56), arrowprops=dict(arrowstyle="->", color="#d97706", lw=1.2, linestyle=":"))
ax.annotate("", xy=(75, 73), xytext=(66, 45), arrowprops=arrow_kw)
ax.annotate("", xy=(75, 62.5), xytext=(66, 43), arrowprops=arrow_kw)
ax.annotate("", xy=(50, 53), xytext=(50, 68), arrowprops=arrow_kw)
ax.annotate("", xy=(50, 38), xytext=(50, 53), arrowprops=arrow_kw)
ax.annotate("", xy=(28, 24), xytext=(40, 38), arrowprops=dict(arrowstyle="<->", color="#475569", lw=1.2, linestyle="--"))
ax.annotate("", xy=(72, 24), xytext=(60, 38), arrowprops=dict(arrowstyle="<->", color="#475569", lw=1.2, linestyle="--"))

plt.tight_layout()
plt.savefig("report_assets/block_diagram.png", dpi=300, bbox_inches="tight")
plt.close()
print("✓ Created report_assets/block_diagram.png")


# ---------------------------------------------------------------------------
# 2. WORKFLOW FLOWCHART
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 10.5), dpi=300)
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")
fig.patch.set_facecolor("#ffffff")

# Titles
ax.text(50, 98, "Multi-Agent Decision & Workflow Flowchart", ha="center", va="center", fontsize=12, fontweight="bold", color="#0f172a")
ax.text(50, 95.5, "LangGraph StateGraph State Machine with Human-in-the-Loop Interrupts", ha="center", va="center", fontsize=8.5, color="#64748b")

# Helper for rounded box
def draw_node(x, y, w, h, title, sub="", color="#1a237e", bg="#ffffff", shape="rect"):
    if shape == "ellipse":
        p = patches.FancyBboxPatch((x-w/2, y-h/2), w, h, boxstyle="round,pad=0.3", facecolor=bg, edgecolor=color, linewidth=1.5)
    elif shape == "diamond":
        p = patches.Polygon([[x, y+h/2], [x+w/2, y], [x, y-h/2], [x-w/2, y]], closed=True, facecolor=bg, edgecolor=color, linewidth=1.5)
    else:
        p = patches.FancyBboxPatch((x-w/2, y-h/2), w, h, boxstyle="round,pad=0.2", facecolor=bg, edgecolor=color, linewidth=1.3)
    ax.add_patch(p)
    if sub:
        ax.text(x, y+1.2, title, ha="center", va="center", fontsize=8, fontweight="bold", color=color)
        ax.text(x, y-1.4, sub, ha="center", va="center", fontsize=6.5, color="#475569")
    else:
        ax.text(x, y, title, ha="center", va="center", fontsize=8, fontweight="bold", color=color)

# Nodes
# 1. Start
draw_node(50, 91, 38, 4.5, "START: Natural-Language User Request", "UI Query + Active Dataset Scope", color="#1a237e", bg="#eff6ff", shape="ellipse")

# 2. Agent 1 Node
draw_node(50, 81, 46, 7.5, "AGENT 1: Expense Analysis Node", "NLU Intent Extraction, Entity Matching & Date Normalization\nDeterministic Columnar Filtering (Pandas Engine)", color="#1e3a8a", bg="#f8fafc")

# 3. Zero Match Decision
draw_node(50, 69, 36, 7, "Records Matched > 0?", "Evaluate Filtered Dataset", color="#b45309", bg="#fffbeb", shape="diamond")

# Zero match abort
draw_node(86, 69, 22, 5, "Abort with Clear Notice", "Zero match explanation", color="#dc2626", bg="#fef2f2")

# 4. Agent 2 Node
draw_node(50, 56, 46, 7.5, "AGENT 2: Validation Agent Node", "Audit against Corporate Limits, Missing Receipts\nNull & Zero Values Check, Prior Auditor Memory Check", color="#d97706", bg="#f8fafc")

# 5. Validation Condition
draw_node(50, 44, 38, 7, "Issues Detected?", "Unresolved Policy Violations", color="#b45309", bg="#fffbeb", shape="diamond")

# 6. HITL Interrupt Node (Left Branch)
draw_node(18, 33, 30, 9, "HITL INTERRUPT", "LangGraph GraphInterrupt Checkpoint\nUser Inputs Values or Excludes Rows\nAuditor Resolves in Compliance Tab", color="#dc2626", bg="#fef2f2")

# 7. Agent 3 Node
draw_node(50, 24, 46, 7.5, "AGENT 3: Report Generation Node", "Mathematical Integrity Guard (Pandas Verification)\nReportLab PDF Generation & Vector Audit Badge", color="#059669", bg="#f8fafc")

# 8. Memory Archival & Email
draw_node(50, 12, 46, 6.5, "Memory Archival & Executive Email Node", "Save report_runs_v2, audit_events to SQLite\nAutonomous Email Draft (Qwen 3) + Dispatch", color="#2563eb", bg="#eff6ff")

# 9. End
draw_node(50, 3.5, 30, 4, "END: Workflow Completed", "Verified PDF Download & Dispatched", color="#059669", bg="#ecfdf5", shape="ellipse")

# Arrows
arr = dict(arrowstyle="->", color="#1e3a8a", lw=1.3)
ax.annotate("", xy=(50, 84.75), xytext=(50, 88.75), arrowprops=arr)
ax.annotate("", xy=(50, 72.5), xytext=(50, 77.25), arrowprops=arr)
ax.annotate("", xy=(50, 59.75), xytext=(50, 65.5), arrowprops=arr)
ax.text(52, 63, "Yes (Count > 0)", fontsize=6.8, color="#059669", fontweight="bold")

# No to Abort
ax.annotate("", xy=(75, 69), xytext=(68, 69), arrowprops=arr)
ax.text(70, 70.2, "No", fontsize=6.8, color="#dc2626", fontweight="bold")
ax.annotate("", xy=(86, 3.5), xytext=(86, 66.5), arrowprops=dict(arrowstyle="->", color="#dc2626", lw=1.2, linestyle="--"))
ax.annotate("", xy=(65, 3.5), xytext=(86, 3.5), arrowprops=dict(arrowstyle="->", color="#dc2626", lw=1.2, linestyle="--"))

# Validation branches
ax.annotate("", xy=(50, 27.75), xytext=(50, 40.5), arrowprops=arr)
ax.text(52, 35, "No Issues\n(Clear)", fontsize=6.8, color="#059669", fontweight="bold")

# Issues branch to HITL
ax.annotate("", xy=(31, 44), xytext=(18, 44), arrowprops=dict(arrowstyle="-", color="#dc2626", lw=1.3))
ax.annotate("", xy=(18, 37.5), xytext=(18, 44), arrowprops=arr)
ax.text(22, 45.2, "Yes (Violations Found)", fontsize=6.8, color="#dc2626", fontweight="bold")

# HITL back to Agent 2 or Agent 3 via Command(resume)
ax.annotate("", xy=(18, 24), xytext=(18, 28.5), arrowprops=dict(arrowstyle="-", color="#2563eb", lw=1.3))
ax.annotate("", xy=(27, 24), xytext=(18, 24), arrowprops=arr)
ax.text(19, 21.5, "Command(resume=action)\nExclude / Correct / Authorize", fontsize=6.2, color="#2563eb", fontweight="bold")

# Agent 3 to Archival
ax.annotate("", xy=(50, 15.25), xytext=(50, 20.25), arrowprops=arr)

# Archival to End
ax.annotate("", xy=(50, 5.5), xytext=(50, 8.75), arrowprops=arr)

plt.tight_layout()
plt.savefig("report_assets/flowchart.png", dpi=300, bbox_inches="tight")
plt.close()
print("✓ Created report_assets/flowchart.png")
