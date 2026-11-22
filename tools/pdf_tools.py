"""
PDF report generation tool using ReportLab.

Generates a professional expense report PDF suitable for
submission to Finance. All layout and formatting is handled
here — no LLM involvement. Supports both single-employee
and multi-employee reports (separate section per person within
a single unified PDF).
"""

import os
import math
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    HRFlowable,
    PageBreak,
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT


# --- Color Palette ---
PRIMARY = colors.HexColor("#1a237e")       # Deep indigo
ACCENT = colors.HexColor("#283593")        # Slightly lighter indigo
HEADER_BG = colors.HexColor("#1a237e")
HEADER_FG = colors.white
ROW_ALT = colors.HexColor("#f5f5f5")       # Light grey alternating rows
BORDER = colors.HexColor("#bdbdbd")
TOTAL_BG = colors.HexColor("#e8eaf6")      # Light indigo
WARNING_BG = colors.HexColor("#fff3e0")    # Light orange for warnings
WARNING_TEXT = colors.HexColor("#e65100")   # Dark orange

# --- Validation Status Badges ---
SUCCESS_BG = colors.HexColor("#e8f5e9")
SUCCESS_BORDER = colors.HexColor("#2e7d32")
SUCCESS_TEXT = colors.HexColor("#1b5e20")
EXCEPTION_BG = colors.HexColor("#fff8e1")
EXCEPTION_BORDER = colors.HexColor("#f57f17")
EXCEPTION_TEXT = colors.HexColor("#b78103")


def _build_status_banner(validation_status: str, validation_notes: list = None) -> Table:
    """Build a styled banner callout displaying the official audit validation status."""
    v_norm = str(validation_status).strip().lower()
    
    if "exception" in v_norm:
        bg_col = EXCEPTION_BG
        border_col = EXCEPTION_BORDER
        text_col = EXCEPTION_TEXT
        title = "VALIDATION STATUS: REVIEWED WITH DOCUMENTED EXCEPTIONS"
        desc = "This report contains flagged items authorized under exception policy with reviewer notes."
    elif "needs" in v_norm or "review" in v_norm or "unresolved" in v_norm:
        bg_col = WARNING_BG
        border_col = colors.HexColor("#ff9800")
        text_col = WARNING_TEXT
        title = "VALIDATION STATUS: AWAITING HUMAN REVIEW (UNRESOLVED DISCREPANCIES)"
        desc = "Preliminary draft. This report has outstanding items requiring reviewer decision."
    else:
        bg_col = SUCCESS_BG
        border_col = SUCCESS_BORDER
        text_col = SUCCESS_TEXT
        title = "VALIDATION STATUS: VERIFIED & CLEAR (ZERO OUTSTANDING ISSUES)"
        desc = "All transactions passed automated compliance, receipt completeness, and arithmetic audits."
        
    p_style_title = ParagraphStyle(
        "BannerTitle",
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=text_col,
        leading=12,
    )
    p_style_body = ParagraphStyle(
        "BannerBody",
        fontName="Helvetica",
        fontSize=8,
        textColor=colors.HexColor("#333333"),
        leading=11,
    )
    
    content = [
        Paragraph(title, p_style_title),
        Paragraph(desc, p_style_body),
    ]
    
    if validation_notes:
        for note in validation_notes[:3]:
            content.append(Paragraph(f"• Note: {note}", p_style_body))
            
    banner_table = Table([[content]], colWidths=[500])
    banner_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg_col),
        ("BOX", (0, 0), (-1, -1), 1, border_col),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return banner_table


def _build_expense_table(expenses: list[dict]) -> Table:
    """Build a styled ReportLab Table for expense line items."""
    table_header = ["#", "Date", "Description", "Merchant", "Category", "Amount (₹)", "Receipt"]
    table_data = [table_header]
    
    sorted_expenses = sorted(expenses, key=lambda x: x.get("date", ""))
    
    for idx, exp in enumerate(sorted_expenses, 1):
        date_str = exp.get("date", "")
        try:
            date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d-%b-%Y")
        except (ValueError, TypeError):
            date_display = str(date_str)
        
        raw_amt = exp.get("amount", 0)
        try:
            amt_num = float(raw_amt) if raw_amt is not None else 0.0
            if math.isnan(amt_num) or math.isinf(amt_num):
                amt_num = 0.0
        except (ValueError, TypeError):
            amt_num = 0.0

        receipt = exp.get("receipt_status", "N/A")
        
        desc = exp.get("description", "")
        if len(desc) > 26:
            desc = desc[:23] + "..."
        
        merchant = exp.get("merchant", "")
        if len(merchant) > 16:
            merchant = merchant[:13] + "..."
        
        row = [
            str(idx),
            date_display,
            desc,
            merchant,
            exp.get("category", "Other"),
            f"{amt_num:,.2f}",
            str(receipt),
        ]
        table_data.append(row)
    
    col_widths = [25, 70, 120, 80, 75, 70, 60]
    expense_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    table_style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (5, 0), (5, -1), "RIGHT"),
        ("ALIGN", (6, 0), (6, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            table_style_commands.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
        receipt_val = str(table_data[i][6]).lower() if len(table_data[i]) > 6 else ""
        if receipt_val in ("missing", "no", "n/a"):
            table_style_commands.append(("TEXTCOLOR", (6, i), (6, i), WARNING_TEXT))
            table_style_commands.append(("FONTNAME", (6, i), (6, i), "Helvetica-Bold"))
    
    expense_table.setStyle(TableStyle(table_style_commands))
    return expense_table


def _build_category_table(category_totals: dict, category_counts: dict, grand_total: float, trans_count: int) -> Table:
    """Build a styled category summary table."""
    summary_header = ["Category", "Transactions", "Amount (₹)", "% of Total"]
    summary_data = [summary_header]
    
    for cat in sorted(category_totals.keys()):
        amount = category_totals[cat]
        count = category_counts.get(cat, 0)
        pct = (amount / grand_total * 100) if grand_total > 0 else 0
        summary_data.append([
            cat,
            str(count),
            f"{amount:,.2f}",
            f"{pct:.1f}%",
        ])
    
    summary_data.append([
        "SUBTOTAL" if grand_total > 0 else "TOTAL",
        str(trans_count),
        f"{grand_total:,.2f}",
        "100.0%",
    ])
    
    summary_table = Table(summary_data, colWidths=[150, 90, 120, 80])
    summary_style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, -1), (-1, -1), TOTAL_BG),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, -1), (-1, -1), PRIMARY),
    ]
    for i in range(1, len(summary_data) - 1):
        if i % 2 == 0:
            summary_style_commands.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    
    summary_table.setStyle(TableStyle(summary_style_commands))
    return summary_table


def generate_pdf(
    expenses: list[dict],
    totals: dict,
    missing_data: list[dict],
    employee_name: str,
    start_date: str,
    end_date: str,
    output_dir: str = None,
    validation_status: str = "Clear",
    validation_notes: list = None,
    report_id: str = None,
) -> str:
    """
    Generate a professional PDF expense report.
    If multiple employees are in `expenses`, generates a single combined PDF
    containing an executive summary and distinct individual sections for each person.
    
    Args:
        expenses: List of expense dicts.
        totals: Dict from calculate_totals().
        missing_data: List of validation issues.
        employee_name: Name of employee (or 'Company Team').
        start_date: Period start (YYYY-MM-DD).
        end_date: Period end (YYYY-MM-DD).
        output_dir: Output directory (defaults to EXPENSE_REPORTS_DIR or 'reports').
        validation_status: Audit status ('Clear', 'Reviewed with Exceptions', 'Needs Human Review').
        validation_notes: Reviewer exception notes to include.
        report_id: Stable identifier for this report run.
        
    Returns:
        Absolute path to the generated PDF.
    """
    output_dir = output_dir or os.getenv("EXPENSE_REPORTS_DIR", "reports")
    os.makedirs(output_dir, exist_ok=True)
    
    if not start_date or not end_date:
        valid_dates = [
            str(exp.get("date") or exp.get("expense_date", "")).strip()[:10]
            for exp in expenses
            if str(exp.get("date") or exp.get("expense_date", "")).strip() not in ("", "None", "nan")
        ]
        if valid_dates:
            sorted_dates = sorted(valid_dates)
            start_date = start_date or sorted_dates[0]
            end_date = end_date or sorted_dates[-1]
        else:
            now = datetime.now()
            start_date = start_date or now.strftime("%Y-%m-01")
            end_date = end_date or now.strftime("%Y-%m-%d")

    try:
        start_dt = datetime.strptime(str(start_date)[:10], "%Y-%m-%d")
    except Exception:
        start_dt = datetime.now()
    try:
        end_dt = datetime.strptime(str(end_date)[:10], "%Y-%m-%d")
    except Exception:
        end_dt = datetime.now()

    month_name = start_dt.strftime("%B")
    year = start_dt.strftime("%Y")
    
    # Check for distinct employees in expenses
    unique_employees = sorted(list({
        str(exp.get("employee", "")).strip()
        for exp in expenses
        if exp.get("employee") and str(exp.get("employee", "")).strip()
    }))
    
    is_multi_employee = len(unique_employees) > 1
    
    if is_multi_employee:
        filename = f"expense_report_{month_name}_{year}_all_employees.pdf"
    else:
        emp_slug = employee_name.replace(" ", "_").replace("/", "_")
        filename = f"expense_report_{month_name}_{year}_{emp_slug}.pdf"
        
    filepath = os.path.join(output_dir, filename)
    abs_path = os.path.abspath(filepath)
    
    doc = SimpleDocTemplate(
        abs_path,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    
    styles = getSampleStyleSheet()
    elements = []
    
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=20,
        textColor=PRIMARY,
        spaceAfter=4,
        alignment=TA_CENTER,
        fontName="Helvetica-Bold",
    )
    
    section_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=PRIMARY,
        spaceBefore=12,
        spaceAfter=6,
        fontName="Helvetica-Bold",
    )
    
    warning_style = ParagraphStyle(
        "WarningText",
        parent=styles["Normal"],
        fontSize=8,
        textColor=WARNING_TEXT,
        leading=11,
    )
    
    period_str = f"{start_dt.strftime('%d %B %Y')} — {end_dt.strftime('%d %B %Y')}"
    generated_str = datetime.now().strftime("%d %B %Y, %I:%M %p")
    grand_total = totals.get("grand_total", 0.0)
    
    # =========================================================================
    # MULTI-EMPLOYEE REPORT
    # =========================================================================
    if is_multi_employee:
        # Title
        elements.append(Paragraph("COMPANY TRAVEL EXPENSE REPORT", title_style))
        elements.append(Paragraph(f"Consolidated Report for {len(unique_employees)} Employees", ParagraphStyle("Sub", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#616161"), alignment=TA_CENTER, spaceAfter=6)))
        elements.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceBefore=2, spaceAfter=10))
        
        # Meta Table
        meta_data = [
            ["Reporting Period:", period_str, "Employees Included:", str(len(unique_employees))],
            ["Generated Date:", generated_str, "Grand Total:", f"₹{grand_total:,.2f}"],
            ["Report Run ID:", report_id or "Auto-Generated", "Validation Status:", validation_status],
        ]
        meta_table = Table(meta_data, colWidths=[95, 175, 110, 120])
        meta_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), PRIMARY),
            ("TEXTCOLOR", (2, 0), (2, -1), PRIMARY),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 8))
        elements.append(_build_status_banner(validation_status, validation_notes))
        elements.append(Spacer(1, 10))
        
        # Executive Summary Table
        elements.append(Paragraph("Executive Summary (All Employees)", section_style))
        emp_breakdown = totals.get("employee_breakdown", {})
        
        exec_header = ["#", "Employee Name", "Transactions", "Subtotal (₹)", "Missing Receipts", "% of Total"]
        exec_data = [exec_header]
        
        for idx, emp in enumerate(unique_employees, 1):
            emp_info = emp_breakdown.get(emp, {})
            emp_amt = emp_info.get("grand_total", sum(x.get("amount", 0) for x in expenses if x.get("employee") == emp))
            emp_cnt = emp_info.get("transaction_count", len([x for x in expenses if x.get("employee") == emp]))
            emp_missing = emp_info.get("missing_receipt_total", 0.0)
            pct = (emp_amt / grand_total * 100) if grand_total > 0 else 0
            
            missing_str = f"₹{emp_missing:,.2f}" if emp_missing > 0 else "None"
            exec_data.append([
                str(idx),
                emp,
                str(emp_cnt),
                f"{emp_amt:,.2f}",
                missing_str,
                f"{pct:.1f}%",
            ])
            
        exec_data.append([
            "TOTAL",
            f"{len(unique_employees)} Employees",
            str(totals.get("transaction_count", len(expenses))),
            f"{grand_total:,.2f}",
            f"₹{totals.get('missing_receipt_total', 0):,.2f}",
            "100.0%",
        ])
        
        exec_table = Table(exec_data, colWidths=[25, 140, 75, 95, 95, 70])
        exec_style = [
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), HEADER_FG),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (2, 0), (2, -1), "CENTER"),
            ("ALIGN", (3, 0), (3, -1), "RIGHT"),
            ("ALIGN", (4, 0), (4, -1), "CENTER"),
            ("ALIGN", (5, 0), (5, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("BACKGROUND", (0, -1), (-1, -1), TOTAL_BG),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, -1), (-1, -1), PRIMARY),
        ]
        for i in range(1, len(exec_data) - 1):
            if i % 2 == 0:
                exec_style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
        exec_table.setStyle(TableStyle(exec_style))
        elements.append(exec_table)
        elements.append(Spacer(1, 14))
        
        # Overall Category Summary
        elements.append(Paragraph("Overall Category Summary", section_style))
        cat_table = _build_category_table(
            totals.get("category_totals", {}),
            totals.get("category_counts", {}),
            grand_total,
            totals.get("transaction_count", len(expenses)),
        )
        elements.append(cat_table)
        
        # Individual Sections for Each Person
        for emp in unique_employees:
            elements.append(PageBreak())
            
            emp_expenses = [x for x in expenses if str(x.get("employee", "")).strip() == emp]
            emp_subtotal = sum(x.get("amount", 0) for x in emp_expenses)
            
            # Individual Header
            elements.append(Paragraph(f"EXPENSE REPORT: {emp.upper()}", title_style))
            elements.append(HRFlowable(width="100%", thickness=1.5, color=ACCENT, spaceBefore=2, spaceAfter=8))
            
            ind_meta = [
                ["Employee:", emp, "Period:", period_str],
                ["Transactions:", str(len(emp_expenses)), "Employee Subtotal:", f"₹{emp_subtotal:,.2f}"],
            ]
            ind_meta_table = Table(ind_meta, colWidths=[90, 180, 100, 130])
            ind_meta_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (0, 0), (0, -1), PRIMARY),
                ("TEXTCOLOR", (2, 0), (2, -1), PRIMARY),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            elements.append(ind_meta_table)
            elements.append(Spacer(1, 8))
            
            # Line items table
            elements.append(Paragraph(f"Transactions for {emp}", section_style))
            elements.append(_build_expense_table(emp_expenses))
            elements.append(Spacer(1, 10))
            
            # Category subtotal table for this employee
            emp_cats = {}
            emp_cat_counts = {}
            for e in emp_expenses:
                c = e.get("category", "Other")
                emp_cats[c] = emp_cats.get(c, 0.0) + float(e.get("amount", 0))
                emp_cat_counts[c] = emp_cat_counts.get(c, 0) + 1
                
            elements.append(Paragraph(f"Category Breakdown ({emp})", section_style))
            elements.append(_build_category_table(emp_cats, emp_cat_counts, emp_subtotal, len(emp_expenses)))
            elements.append(Spacer(1, 10))
            
            # Missing receipts for this employee
            emp_missing_issues = [
                m for m in missing_data
                if m.get("expense", {}).get("employee") == emp and m.get("issue_type") == "missing_receipt"
            ]
            if emp_missing_issues:
                elements.append(Paragraph(f"Missing Documentation ({emp})", section_style))
                for iss in emp_missing_issues:
                    e = iss.get("expense", {})
                    elements.append(Paragraph(
                        f"⚠ {e.get('description', '')} — {e.get('merchant', '')} — ₹{e.get('amount', 0):,.2f} (Receipt: Missing)",
                        warning_style,
                    ))
                elements.append(Spacer(1, 6))

    # =========================================================================
    # SINGLE-EMPLOYEE REPORT
    # =========================================================================
    else:
        disp_emp = employee_name if employee_name else (unique_employees[0] if unique_employees else "Employee")
        elements.append(Paragraph("TRAVEL EXPENSE REPORT", title_style))
        elements.append(Spacer(1, 2))
        elements.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceBefore=2, spaceAfter=12))
        
        meta_data = [
            ["Employee:", disp_emp, "Reporting Period:", period_str],
            ["Generated:", generated_str, "Total Expenses:", f"₹{grand_total:,.2f}"],
            ["Report Run ID:", report_id or "Auto-Generated", "Validation Status:", validation_status],
        ]
        meta_table = Table(meta_data, colWidths=[80, 170, 100, 150])
        meta_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), PRIMARY),
            ("TEXTCOLOR", (2, 0), (2, -1), PRIMARY),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 8))
        elements.append(_build_status_banner(validation_status, validation_notes))
        elements.append(Spacer(1, 10))
        
        elements.append(Paragraph("Expense Details", section_style))
        elements.append(_build_expense_table(expenses))
        elements.append(Spacer(1, 14))
        
        elements.append(Paragraph("Category Summary", section_style))
        elements.append(_build_category_table(
            totals.get("category_totals", {}),
            totals.get("category_counts", {}),
            grand_total,
            totals.get("transaction_count", len(expenses)),
        ))
        elements.append(Spacer(1, 14))
        
        missing_receipt_issues = [
            m for m in missing_data if m.get("issue_type") == "missing_receipt"
        ]
        if missing_receipt_issues:
            elements.append(Paragraph("Missing Documentation", section_style))
            for issue in missing_receipt_issues:
                exp = issue.get("expense", {})
                elements.append(Paragraph(
                    f"⚠ {exp.get('description', 'Unknown')} — {exp.get('merchant', '')} — ₹{exp.get('amount', 0):,.2f} — Receipt: Missing",
                    warning_style,
                ))
            elements.append(Spacer(1, 6))

    # =========================================================================
    # FOOTER
    # =========================================================================
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceBefore=8, spaceAfter=6))
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#9e9e9e"),
        alignment=TA_CENTER,
    )
    elements.append(Paragraph(
        "This report was generated by the AI Expense Report Agent. Please verify all entries before processing.",
        footer_style,
    ))
    elements.append(Paragraph(f"Generated on {generated_str}", footer_style))
    
    doc.build(elements)
    return abs_path
