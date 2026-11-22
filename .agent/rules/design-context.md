# Persistent Design Guidelines: AI Expense Report Agent

These guidelines establish the persistent design context for all future UI/UX modifications to the AI Expense Report Agent.

## Core Identity
- **Users**: Corporate Finance Managers, Controllers, and Compliance Auditors.
- **Brand Personality**: **Authoritative, Crisp, Trustworthy** (inspired by Stripe, Ramp, Mercury).
- **Theme**: Crisp Light Theme with slate-tinted backgrounds (`#f8fafc`), clean white card surfaces (`#ffffff`), and deep navy/indigo brand anchors (`#1a237e`, `#0f172a`).

## Visual Design Tokens
- **Primary Brand**: `#1a237e` (Deep Indigo / Navy)
- **Secondary Accent**: `#2563eb` (Royal Blue)
- **Canvas Background**: `#f8fafc` (Soft Crisp Slate)
- **Surface Containers**: `#ffffff` with `#e2e8f0` borders and subtle box-shadows
- **Typography**: Clean sans-serif with `font-variant-numeric: tabular-nums` for all financial figures, currencies, dates, and tables.
- **Semantic Status Badges**:
  - `VERIFIED & CLEAR`: Emerald Green (`#059669` text, `#ecfdf5` background, `#a7f3d0` border)
  - `REVIEWED WITH EXCEPTIONS`: Amber (`#d97706` text, `#fffbeb` background, `#fde68a` border)
  - `NEEDS HUMAN REVIEW`: Crimson (`#dc2626` text, `#fef2f2` background, `#fecaca` border)
  - `PROCESSING`: Blue (`#2563eb` text, `#eff6ff` background, `#bfdbfe` border)

## Practical Design Principles
1. **Zero Silent Approvals**: Unresolved validation issues must never be treated as approved; always require explicit human decision.
2. **Tabular Clarity**: High contrast, tabular numerals for currency figures, and readable column alignments.
3. **Truthful Multi-Agent States**: Discrete, honest progress indicators for Expense Analysis Agent, Validation Agent, and Report Generation Agent.
4. **Action Hierarchy**: Clear separation of primary execution buttons, exception management buttons, PDF download, and email dispatch.
5. **Persistent System Cohesion**: Unified styling across Dashboard, History, Persistent SQLite Memory, and Compliance Audit.
