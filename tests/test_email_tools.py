"""
Tests for email_tools module:
- Qwen 3 / Template draft generation
- Email validation
- Attachment validation
- SMTP / Resend Simulation mode
"""

import os
import shutil
import tempfile
import unittest
from tools.email_tools import generate_email_draft, send_email_report


class TestEmailTools(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.mock_totals = {
            "grand_total": 45200.0,
            "category_totals": {
                "Flight": 25000.0,
                "Hotel": 15000.0,
                "Meals": 5200.0,
            },
            "transaction_count": 8,
            "missing_receipt_total": 0.0,
        }
        self.dummy_pdf = os.path.join(self.test_dir, "test_dummy_report.pdf")
        with open(self.dummy_pdf, "wb") as f:
            f.write(b"%PDF-1.4 test expense report content")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_generate_email_draft_structure(self):
        """Test draft generation produces non-empty subject and body."""
        draft = generate_email_draft(
            totals=self.mock_totals,
            employee_name="Priya Sharma",
            start_date="2026-07-01",
            end_date="2026-07-31",
            expense_type="travel",
        )
        self.assertIn("subject", draft)
        self.assertIn("body", draft)
        self.assertIn("source", draft)
        self.assertTrue(len(draft["subject"]) > 5)
        self.assertTrue(len(draft["body"]) > 20)
        self.assertIn("Priya Sharma", draft["subject"] + draft["body"])
        self.assertIn("45,200", draft["subject"] + draft["body"])

    def test_send_email_invalid_address(self):
        """Test sending to an invalid address returns an error."""
        res = send_email_report(
            to_email="invalid-email-address",
            subject="Test Subject",
            body="Test Body",
            pdf_path=self.dummy_pdf,
        )
        self.assertFalse(res["success"])
        self.assertIn("Invalid recipient email", res["message"])

    def test_send_email_missing_pdf(self):
        """Test sending with non-existent PDF returns an error."""
        res = send_email_report(
            to_email="manager@example.com",
            subject="Test Subject",
            body="Test Body",
            pdf_path=os.path.join(self.test_dir, "non_existent_file.pdf"),
        )
        self.assertFalse(res["success"])
        self.assertIn("does not exist", res["message"])

    def test_send_email_resend_simulation_mode(self):
        """Test Resend simulation mode when API key is empty."""
        res = send_email_report(
            to_email="phadshubham44@gmail.com",
            subject="[Expense Report] Travel - Priya Sharma",
            body="Please find attached the report.",
            pdf_path=self.dummy_pdf,
            resend_api_key="",
        )
        self.assertTrue(res["success"])
        self.assertTrue(res["simulated"])
        self.assertIn("Resend", res["message"])
        self.assertEqual(res["details"]["attachment"], os.path.basename(self.dummy_pdf))

    def test_send_email_resend_with_configured_key(self):
        """Test Resend setup recognizes configured API key."""
        key = "re_test_mock_123456"
        res = send_email_report(
            to_email="phadshubham44@gmail.com",
            subject="[Expense Report] Travel - Priya Sharma",
            body="Please find attached the report.",
            pdf_path=self.dummy_pdf,
            resend_api_key=key,
        )
        self.assertIn("Resend", res["message"])


if __name__ == "__main__":
    unittest.main()
