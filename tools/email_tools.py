"""
Email tools for the AI Expense Report Agent.

Provides:
- generate_email_draft: Uses Qwen 3 (via Ollama) to draft an executive subject line
  and professional email body summarizing the expense report, with fallback handling.
- send_email_report / send_email_via_resend: Dispatches the email with the generated PDF
  report attached via the Resend REST API (free 3,000 emails/month).
"""

import os
import re
import json
import base64
import requests
from typing import Optional, Dict, Any


def _is_ollama_online(base_url: str, timeout: float = 0.5) -> bool:
    """Quick socket check to test if the Ollama server is reachable."""
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(base_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 11434
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _get_llm(model_name: Optional[str] = None, base_url: Optional[str] = None):
    """Initialize the local LLM via Ollama for email generation."""
    try:
        url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        if not _is_ollama_online(url):
            return None

        from langchain_ollama import ChatOllama

        model = model_name or os.getenv("OLLAMA_MODEL", "qwen3:4b")

        return ChatOllama(
            model=model,
            base_url=url,
            temperature=0.3,
            num_predict=700,
        )
    except Exception:
        return None


def generate_email_draft(
    totals: Dict[str, Any],
    employee_name: str = "Employee",
    start_date: str = "",
    end_date: str = "",
    expense_type: str = "travel",
    missing_data: Optional[list] = None,
    model_name: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, str]:
    """
    Generate an executive subject line and corporate email body summarizing the report.
    
    Uses Qwen 3 via Ollama if available, with a structured corporate fallback template.
    
    Returns:
        dict: {"subject": str, "body": str, "source": "qwen3" | "template"}
    """
    grand_total = totals.get("grand_total", 0.0) if totals else 0.0
    cat_totals = totals.get("category_totals", {}) if totals else {}
    tx_count = totals.get("transaction_count", 0) if totals else 0
    missing_receipt_total = totals.get("missing_receipt_total", 0.0) if totals else 0.0

    category_summary = ", ".join(
        f"{cat}: ₹{amt:,.0f}" for cat, amt in sorted(cat_totals.items())
    ) or "None"

    compliance_note = ""
    if missing_data:
        compliance_note = f"{len(missing_data)} flagged transaction(s) requiring compliance review."
    elif missing_receipt_total > 0:
        compliance_note = f"₹{missing_receipt_total:,.0f} in transactions flagged with missing receipts."

    # Try LLM generation via Qwen 3
    llm = _get_llm(model_name=model_name, base_url=base_url)
    if llm:
        prompt = f"""You are an executive assistant drafting a formal expense report email.
Report Details:
- Employee: {employee_name}
- Period: {start_date} to {end_date}
- Expense Type: {expense_type.title()} Expenses
- Grand Total: ₹{grand_total:,.2f}
- Transaction Count: {tx_count}
- Breakdown: {category_summary}
- Receipt Verification: {compliance_note or 'All receipts attached and verified'}

Instructions:
1. Write a professional Subject Line summarizing the employee, period, and total amount.
2. Write a clear, polite email body addressed to the Finance & Approvals Team summarizing the key figures and explicitly noting that the generated expense report PDF is attached.
3. Sign off respectfully on behalf of {employee_name}.

Respond ONLY with a JSON object in this exact format (NO markdown fences, NO extra text):
{{"subject": "...", "body": "..."}}"""

        try:
            response = llm.invoke(prompt)
            content = response.content.strip()

            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                subject = str(parsed.get("subject", "")).strip()
                body = str(parsed.get("body", "")).strip()
                if subject and body:
                    return {
                        "subject": subject,
                        "body": body,
                        "source": "qwen3",
                    }
        except Exception:
            pass

    # Structured Corporate Template Fallback
    period_str = f"({start_date} to {end_date})" if start_date and end_date else ""
    subject = f"[Expense Report] {expense_type.title()} Expenses - {employee_name} {period_str} - ₹{grand_total:,.0f}".strip()

    compliance_line = f"\n• Compliance: {compliance_note}" if compliance_note else "\n• Receipts: All verified & documented"

    body = f"""Dear Finance & Approvals Team,

Please find attached the official expense report for {employee_name} for the period {start_date} to {end_date}.

Summary of Expenses:
• Total Amount: ₹{grand_total:,.2f}
• Total Transactions: {tx_count}
• Category Breakdown: {category_summary}{compliance_line}

The itemized PDF report is attached to this email for your review and reimbursement processing.

Best regards,
{employee_name}"""

    return {
        "subject": subject,
        "body": body,
        "source": "template",
    }


def send_email_via_resend(
    api_key: str,
    to_email: str,
    subject: str,
    body: str,
    pdf_path: Optional[str] = None,
    from_email: str = "onboarding@resend.dev",
) -> Dict[str, Any]:
    """
    Send an email with attached PDF report via the Resend REST API.
    
    Free tier allows 3,000 emails/month (100/day) with zero credit card needed.
    """
    to_email = (to_email or "").strip()
    if not to_email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to_email):
        return {
            "success": False,
            "simulated": False,
            "message": f"Invalid recipient email address: '{to_email}'",
            "details": {},
        }

    # Validate PDF attachment if provided
    pdf_filename = ""
    pdf_b64 = None
    if pdf_path:
        if os.path.exists(pdf_path):
            try:
                with open(pdf_path, "rb") as f:
                    pdf_data = f.read()
                pdf_b64 = base64.b64encode(pdf_data).decode("utf-8")
                pdf_filename = os.path.basename(pdf_path)
            except Exception as e:
                return {
                    "success": False,
                    "simulated": False,
                    "message": f"Could not read PDF attachment: {e}",
                    "details": {},
                }
        else:
            return {
                "success": False,
                "simulated": False,
                "message": f"PDF report file does not exist: {pdf_path}",
                "details": {},
            }

    api_key = (api_key or "").strip()
    if not api_key:
        return {
            "success": True,
            "simulated": True,
            "message": (
                f"📧 [Resend Simulation Mode] Report email drafted for {to_email}. "
                f"Attachment: '{pdf_filename or 'None'}'. "
                "To send live emails, ensure RESEND_API_KEY is set in your .env file."
            ),
            "details": {
                "to": to_email,
                "from": from_email,
                "subject": subject,
                "attachment": pdf_filename,
            },
        }

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Format HTML body for modern email clients
    html_body = f"""<div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6; color: #222;">
{body.replace(chr(10), '<br>')}
</div>"""

    payload: Dict[str, Any] = {
        "from": from_email.strip() or "onboarding@resend.dev",
        "to": [to_email],
        "subject": subject.strip(),
        "text": body.strip(),
        "html": html_body,
    }

    if pdf_b64 and pdf_filename:
        payload["attachments"] = [
            {
                "filename": pdf_filename,
                "content": pdf_b64,
            }
        ]

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        res_data = response.json() if response.content else {}

        if response.status_code in (200, 201):
            email_id = res_data.get("id", "OK")
            return {
                "success": True,
                "simulated": False,
                "message": f"✅ Email successfully sent via Resend API to {to_email} with '{pdf_filename}' attached! (ID: {email_id})",
                "details": {"id": email_id, "provider": "resend", "to": to_email},
            }
        else:
            err_msg = res_data.get("message", response.text)
            if "testing emails to your own email address" in err_msg.lower():
                err_msg += f" (Tip: On Resend's free onboarding domain, emails can only be sent to your registered account address, e.g. phadshubham44@gmail.com. To send to any recipient, verify your domain at resend.com/domains)."
            elif "api key" in err_msg.lower():
                err_msg += " (Tip: Check your Resend API key at resend.com/api-keys)."

            return {
                "success": False,
                "simulated": False,
                "message": f"Resend API Error ({response.status_code}): {err_msg}",
                "details": res_data,
            }
    except Exception as e:
        return {
            "success": False,
            "simulated": False,
            "message": f"Failed to connect to Resend API: {str(e)}",
            "details": {"error": str(e)},
        }


def send_email_report(
    to_email: str,
    subject: str,
    body: str,
    pdf_path: Optional[str] = None,
    resend_api_key: Optional[str] = None,
    resend_from: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Send the expense report email with attached PDF using the Resend API.
    """
    api_key = resend_api_key or os.getenv("RESEND_API_KEY", "")
    from_email = resend_from or os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev")

    return send_email_via_resend(
        api_key=api_key,
        to_email=to_email,
        subject=subject,
        body=body,
        pdf_path=pdf_path,
        from_email=from_email,
    )
