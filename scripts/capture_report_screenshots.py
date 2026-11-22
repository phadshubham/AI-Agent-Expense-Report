"""
Capture high-resolution screenshots of the Streamlit application for the project report.
"""
import os
import time
from playwright.sync_api import sync_playwright

os.makedirs("report_assets", exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 820})

    print("Navigating to http://localhost:8501...")
    page.goto("http://localhost:8501", wait_until="networkidle")
    page.wait_for_timeout(3000)

    # 1. Executive Workspace & Active Table Editor
    page.screenshot(path="report_assets/step1_workspace.png")
    print("✓ Captured step1_workspace.png")

    # Scroll down to capture Prompt and Multi-Agent Collaboration Stages
    prompt_box = page.locator("textarea").first
    if prompt_box.count() > 0:
        prompt_box.fill("Generate all expenses report for Priya Sharma for August 2026")
        page.wait_for_timeout(500)
    
    page.evaluate("window.scrollTo(0, 600)")
    page.wait_for_timeout(1000)
    page.screenshot(path="report_assets/step2_prompt_stages.png")
    print("✓ Captured step2_prompt_stages.png")

    # Click Execute Multi-Agent Workflow
    exec_btn = page.locator('button:has-text("Execute Multi-Agent Workflow")').first
    if exec_btn.count() > 0:
        exec_btn.click()
        print("Clicked Execute Multi-Agent Workflow... waiting for completion or HITL...")
        # Wait up to 15s for execution to complete or hitl
        for _ in range(15):
            page.wait_for_timeout(1000)
            text = page.content()
            if "Executive Financial Summary" in text or "Compliance Review" in text:
                break
        
        page.evaluate("window.scrollTo(0, 950)")
        page.wait_for_timeout(1000)
        page.screenshot(path="report_assets/step3_execution_result.png")
        print("✓ Captured step3_execution_result.png")

        # Scroll further down to capture PDF and AI Email Dispatch
        page.evaluate("window.scrollTo(0, 1550)")
        page.wait_for_timeout(1000)
        page.screenshot(path="report_assets/step4_pdf_email.png")
        print("✓ Captured step4_pdf_email.png")

    # Scroll back to top
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)

    # Click Tab 2: Prompt & Report Run History
    tabs = page.locator('button[data-baseweb="tab"]')
    if tabs.count() >= 2:
        tabs.nth(1).click()
        page.wait_for_timeout(2000)
        page.evaluate("window.scrollTo(0, 150)")
        page.screenshot(path="report_assets/step5_history.png")
        print("✓ Captured step5_history.png")

    # Click Tab 3: Persistent SQLite Memory
    if tabs.count() >= 3:
        tabs.nth(2).click()
        page.wait_for_timeout(2000)
        page.evaluate("window.scrollTo(0, 180)")
        page.screenshot(path="report_assets/step6_memory.png")
        print("✓ Captured step6_memory.png")

    # Click Tab 4: Compliance & Validation Issues
    if tabs.count() >= 4:
        tabs.nth(3).click()
        page.wait_for_timeout(2000)
        page.evaluate("window.scrollTo(0, 100)")
        page.screenshot(path="report_assets/step7_compliance.png")
        print("✓ Captured step7_compliance.png")

    browser.close()
    print("All screenshots successfully captured!")
