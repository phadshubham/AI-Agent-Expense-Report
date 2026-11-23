"""
Generate a professional, publication-grade PDF from roles/individual_contributions.md.
Uses ReportLab to render clean typography, cards for each member, code blocks, and running headers.
"""
import os
import pypdf
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas

PDF_PATH = "roles/individual_contributions.pdf"
os.makedirs("roles", exist_ok=True)

# Dimensions
PAGE_WIDTH, PAGE_HEIGHT = A4  # 595.28 x 841.89 pt
MARGIN_X = 36.0  # 0.5 in
MARGIN_TOP = 42.0
MARGIN_BOTTOM = 40.0
USABLE_WIDTH = PAGE_WIDTH - 2 * MARGIN_X  # 523.28 pt

# Palette
C_PRIMARY = colors.HexColor("#1a237e")      # Deep Navy / Indigo
C_SECONDARY = colors.HexColor("#0f172a")    # Slate dark
C_ACCENT_BLUE = colors.HexColor("#2563eb")  # Royal blue
C_EMERALD = colors.HexColor("#059669")      # Success green
C_AMBER = colors.HexColor("#d97706")        # Amber alert
C_TEXT_DARK = colors.HexColor("#1e293b")    # Slate 800 body
C_TEXT_MUTED = colors.HexColor("#64748b")   # Slate 500
C_BG_LIGHT = colors.HexColor("#f8fafc")     # Light table row
C_BORDER = colors.HexColor("#cbd5e1")       # Border grey
C_CODE_BG = colors.HexColor("#f1f5f9")      # Monospace grey

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to stamp running header with total page count.
    """
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(C_TEXT_MUTED)

        # Running Top Header on all pages
        header_left = "AI-Powered Expense Report Management System  |  Course: Agentic AI"
        header_right = f"Page {self._pageNumber} of {page_count}"
        self.drawString(MARGIN_X, PAGE_HEIGHT - 28, header_left)
        self.drawRightString(PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - 28, header_right)

        # Subtle separator line
        self.setStrokeColor(C_BORDER)
        self.setLineWidth(0.6)
        self.line(MARGIN_X, PAGE_HEIGHT - 32, PAGE_WIDTH - MARGIN_X, PAGE_HEIGHT - 32)

        self.restoreState()


def build_pdf():
    doc = SimpleDocTemplate(
        PDF_PATH,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=C_PRIMARY,
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=C_TEXT_MUTED,
        spaceAfter=12
    )
    member_header_style = ParagraphStyle(
        "MemberHeader",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=C_PRIMARY,
        spaceBefore=0,
        spaceAfter=4
    )
    topic_style = ParagraphStyle(
        "TopicStyle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=C_SECONDARY,
        spaceBefore=4,
        spaceAfter=2
    )
    bullet_style = ParagraphStyle(
        "BulletText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.2,
        leading=11.2,
        textColor=C_TEXT_DARK,
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=2.5
    )
    code_tag_style = ParagraphStyle(
        "CodeTag",
        parent=styles["Normal"],
        fontName="Courier-Bold",
        fontSize=7.8,
        leading=10.5,
        textColor=C_PRIMARY
    )
    meta_cell = ParagraphStyle(
        "MetaCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10.5,
        textColor=C_TEXT_DARK
    )
    meta_cell_bold = ParagraphStyle(
        "MetaCellBold",
        parent=meta_cell,
        fontName="Helvetica-Bold",
        textColor=C_SECONDARY
    )

    story = []

    # Title Banner
    story.append(Paragraph("Individual Technical Contributions", title_style))
    story.append(Paragraph(
        "AI-Powered Expense Report Management System Using Agentic AI &nbsp;|&nbsp; Course: <b>Agentic AI</b> &nbsp;|&nbsp; Guide: <b>Prof Swapnili Karmore</b>",
        subtitle_style
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=C_ACCENT_BLUE, spaceAfter=10, spaceBefore=0))

    # Helper function to create member card
    def make_member_card(num_str, name, enrollment_id, topics_and_bullets, files_list):
        card_content = []
        
        # Header banner
        header_text = f"<b>{num_str}. {name}</b> &nbsp;&nbsp;<font color='#64748b' size='8'>(Enrollment ID: <b>{enrollment_id}</b>)</font>"
        card_content.append(Paragraph(header_text, member_header_style))
        card_content.append(Spacer(1, 3))
        
        # Topics & Bullets
        for topic_title, bullets in topics_and_bullets:
            card_content.append(Paragraph(f"<b>{topic_title}</b>", topic_style))
            for b in bullets:
                card_content.append(Paragraph(f"• {b}", bullet_style))
            card_content.append(Spacer(1, 2))
            
        # Files authored
        files_html = "<b>Primary Code Files Authored:</b> " + ", ".join([f"<code>{f}</code>" for f in files_list])
        card_content.append(Spacer(1, 3))
        card_content.append(Paragraph(files_html, bullet_style))
        
        # Wrap in table card
        card_table = Table([[card_content]], colWidths=[USABLE_WIDTH])
        card_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), C_BG_LIGHT),
            ('BOX', (0,0), (-1,-1), 1, C_BORDER),
            ('LINELEFT', (0,0), (0,0), 3.5, C_PRIMARY),
            ('TOPPADDING', (0,0), (-1,-1), 7),
            ('BOTTOMPADDING', (0,0), (-1,-1), 7),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ]))
        return card_table

    # 1. Shubham Phad
    shubham_phad_topics = [
        ("LangGraph Multi-Agent Orchestration", [
            "Designed and built the compiled <b>StateGraph</b> workflow coordinating execution handoffs between Agent 1, Agent 2, and Agent 3.",
            "Implemented the centralized state schema (<code>ExpenseAgentState</code>) in <code>state.py</code> to pass data, audit issues, and calculation results between nodes.",
            "Configured conditional routing logic (<code>check_zero_records</code> and <code>check_validation_status</code>) to govern state transitions, zero-record aborts, and human review branches."
        ]),
        ("Agent 1: Expense Analysis Engine", [
            "Developed the natural-language intent parser in <code>tools/expense_tools.py</code> combining local Ollama Qwen 3 inference with a regex fallback parser.",
            "Implemented dynamic fuzzy entity resolution using <b>RapidFuzz</b> to match typed employee names against the active dataset registry.",
            "Built date normalization logic to convert relative expressions (e.g., <i>'last month'</i>, <i>'August 2026'</i>) into strict calendar bounds <code>[start_date, end_date]</code>.",
            "Added boundary diagnostics to prevent silent failures when query criteria fall outside dataset date coverage."
        ]),
        ("Agent 2: Compliance & Policy Auditor", [
            "Programmed compliance evaluation rules in <code>tools/validation_tools.py</code> to audit expenses against corporate caps (₹1,500 single meal, ₹5,000 daily spend, ₹25,000 travel).",
            "Built automatic detection for missing receipts, negative amounts, null values, and out-of-policy claims."
        ]),
        ("Agent 3: Deterministic Arithmetic Core", [
            "Created the <b>Mathematical Integrity Guard</b> in <code>tools/calculation_tools.py</code> using vectorized Pandas operations (sum, count, category subtotals, employee aggregates).",
            "Enforced zero generative LLM math to eliminate arithmetic hallucination."
        ])
    ]
    story.append(make_member_card(
        "1", "Shubham Phad", "ADT23SOCB1106",
        shubham_phad_topics,
        ["agent.py", "state.py", "tools/expense_tools.py", "tools/validation_tools.py", "tools/calculation_tools.py"]
    ))
    story.append(Spacer(1, 10))

    # 2. Shubham Mishra
    shubham_mishra_topics = [
        ("Two-Tier Storage Architecture", [
            "Implemented the storage decoupling between persistent business data (<code>data/expense_memory.db</code>) and runtime workflow state checkpoints (<code>.checkpoints/agent_state.db</code>).",
            "Structured the production relational schema across <code>datasets</code>, <code>expenses_v2</code>, <code>validation_issues_v2</code>, <code>report_runs_v2</code>, <code>audit_events</code>, and <code>import_batches</code>."
        ]),
        ("Cryptographic Dataset Isolation", [
            "Implemented SHA-256 file hashing to compute unique fingerprints for every uploaded CSV file.",
            "Assigned distinct <code>dataset_id</code> identifiers to isolate all stored transactions, validation issues, prompt history, and report snapshots.",
            "Scoped all database query functions in <code>tools/memory_tools.py</code> with <code>WHERE dataset_id = ?</code> to prevent data leakage between different datasets."
        ]),
        ("Content-Signature Deduplication Engine", [
            "Diagnosed and fixed the 340-row duplication bug where re-running workflows duplicated rows.",
            "Developed the content-hash signature pool: <code>ContentHash = SHA-256(date || employee || description || merchant || amount)</code>.",
            "Ensured repeated runs reuse canonical record IDs, preserving the exact 170-row count and ₹609,550.00 total spend."
        ]),
        ("Audit Memory Persistence", [
            "Created database persistence for managerial review decisions (<code>accept_exception</code>, <code>exclude</code>, <code>correct</code>) in <code>validation_issues_v2</code>.",
            "Built immutable historical run logging in <code>report_runs_v2</code> for reproducible report snapshots."
        ])
    ]
    story.append(make_member_card(
        "2", "Shubham Mishra", "ADT23SOCB1110",
        shubham_mishra_topics,
        ["tools/memory_tools.py", "data/expense_memory.db", "tests/test_milestone1_db.py"]
    ))

    story.append(PageBreak())

    # 3. Paras Salunke
    paras_salunke_topics = [
        ("Streamlit Application Interface", [
            "Developed the core user interface in <code>app.py</code> across 4 operational tabs (Executive Workspace, Prompt & Report History, SQLite Memory & Ingestion, Compliance & Validation).",
            "Styled the application using a custom theme with deep navy/indigo headers, slate surfaces, and clean responsive containers."
        ]),
        ("Interactive Source-of-Truth Table Editor", [
            "Integrated <code>st.data_editor</code> as the primary live interface for modifying, adding, and deleting expense transactions.",
            "Implemented dynamic widget keying (<code>key=f'editor_{dataset_id}_{version}'</code>) to prevent loss of user edits during Streamlit reruns.",
            "Created the Save Changes handler to update active dataset versions and sync modifications directly to SQLite memory."
        ]),
        ("Real-Time Table Health & Diagnostics Ribbon", [
            "Built the dynamic financial health ribbon that recalculates live metrics on every user interaction: Active transaction count (170 rows), Live monetary spend (₹609,550.00), Missing receipt count (5 missing), and Null amount count (0 nulls)."
        ]),
        ("Multi-Agent Visual Telemetry", [
            "Designed the Multi-Agent Collaboration Stages monitor tracking live status for Agent 1, Agent 2, and Agent 3.",
            "Built the Chronological Activity & Audit Log displaying sequential execution traces, retrieval counts, and entity match scores."
        ]),
        ("Autonomous Executive Email Dispatch", [
            "Authored <code>tools/email_tools.py</code> to generate and send executive expense summaries.",
            "Integrated local Ollama Qwen 3 (with fallback templates) to draft structured executive briefings.",
            "Integrated the Resend API to dispatch formatted HTML emails with links to generated PDF reports."
        ])
    ]
    story.append(make_member_card(
        "3", "Paras Salunke", "ADT23SOCB0692",
        paras_salunke_topics,
        ["app.py", "tools/email_tools.py", "Custom UI CSS and AgGrid styling"]
    ))
    story.append(Spacer(1, 10))

    # 4. Kaustubh Manjarekar
    kaustubh_topics = [
        ("Human-in-the-Loop (HITL) Review Flow", [
            "Implemented LangGraph <code>interrupt()</code> handling in the workflow to halt execution whenever policy violations or missing receipts are detected.",
            "Handled workflow resumption using <code>Command(resume={'action': action, ...})</code> to apply human decisions without losing graph state."
        ]),
        ("Auditor Direct Resolution Console", [
            "Built managerial resolution controls in the Compliance tab allowing auditors to: <code>accept_exception</code> (approve with justification), <code>exclude</code> (strip from totals), or <code>correct</code> (fix values in storage).",
            "Bound resolution actions to <code>audit_events</code> with timestamps and reviewer IDs for audit compliance."
        ]),
        ("Publication-Grade Vector PDF Generation Engine", [
            "Built the PDF compilation engine in <code>tools/pdf_tools.py</code> using ReportLab flowables.",
            "Implemented official compliance badges (emerald <code>100% COMPLIANT</code> vs amber <code>APPROVED WITH EXCEPTIONS</code>).",
            "Programmed dynamic table pagination, automatic column wrapping, summary metric cards, and running headers."
        ]),
        ("Automated QA Verification Suite", [
            "Authored the entire 324-test automated test suite across 4 verification tiers: Tier 1 (Storage & Isolation - 98 tests), Tier 2 (PDF & Math Guard - 74 tests), Tier 3 (LangGraph & HITL - 82 tests), and Tier 4 (Edge Cases & Resilience - 70 tests).",
            "Verified 100% test pass rate in under 11 seconds (<code>324 passed in 10.68s</code>) with 0 regressions."
        ])
    ]
    story.append(make_member_card(
        "4", "Kaustubh Manjarekar", "ADT23SOCB0510",
        kaustubh_topics,
        ["tools/pdf_tools.py", "tests/test_e2e_tier*.py", "tests/test_tools.py", "scripts/generate_project_report.py"]
    ))

    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"✓ Successfully generated {PDF_PATH}")

if __name__ == "__main__":
    build_pdf()
