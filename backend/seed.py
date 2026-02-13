import asyncio
import secrets
import sys

from sqlalchemy import select, text
from app.config import settings
from app.database import async_session
from app.models import Tenant
from app.services.document import ingest_document

TENANTS = [
    {"name": "Acme Corp", "slug": "acme-corp", "api_key": "ka-acme-test-key-001"},
    {"name": "Beta Inc", "slug": "beta-inc", "api_key": "ka-beta-test-key-002"},
]

DOCUMENTS = {
    "acme-corp": [
        {
            "title": "Annual Leave Policy",
            "content": """# Annual Leave Policy

## Eligibility
All full-time employees who have completed their probation period (90 days) are eligible for annual leave.

## Leave Entitlement
Entitlement is based on years of service:
- 0 to 2 years of service: 10 days per year
- 2 to 5 years of service: 15 days per year
- More than 5 years of service: 20 days per year

## How to Apply for Leave
1. Submit your leave request via the HR Portal at least 3 days in advance.
2. Ensure your team lead approves the request.
3. Once approved, you will receive an email confirmation.

## Unused Leave
Unused leave up to 5 days can be carried over to the next year. Any excess will be forfeited unless special approval is granted by HR.
""",
            "source": "hr/policies/leave_2024.md",
        },
        {
            "title": "IT Support FAQ",
            "content": """# IT Support FAQ

## How do I reset my password?
Go to https://sso.company.com/reset or contact the IT helpdesk at extension 1234. Your password must be at least 12 characters with uppercase, lowercase, numbers, and symbols.

## How do I request a new laptop?
Laptop requests must be submitted by your manager via the IT Procurement form on the Intranet. Standard approval time is 3-5 business days.

## Can I install personal software?
No. Installing personal software on company devices is strictly prohibited. If you need specific software for work, please submit a software request ticket.

## VPN Access
VPN access is granted automatically to all remote employees. Use your standard SSO credentials to log in via the Cisco AnyConnect client.
""",
            "source": "it/support_faq.md",
        },
        {
            "title": "Expense Reimbursement Policy",
            "content": """# Expense Reimbursement Policy

## Meal Allowance
Employees traveling for business can claim up to $50 per day for meals. Receipts are required for any expense over $25.

## Travel Expenses
Flight and hotel bookings should be made through the corporate travel portal. Personal card bookings will only be reimbursed with prior approval from a Director-level manager.

## Submission Deadline
All expense reports must be submitted within 30 days of incurring the expense. Late submissions may be rejected.
""",
            "source": "finance/expenses.md",
        },
    ],
    "beta-inc": [
        {
            "title": "Remote Work Policy",
            "content": """# Remote Work Policy (Beta Inc)

## Core Hours
Employees are expected to be available online during core hours: 10:00 AM to 3:00 PM local time.

## Equipment
The company provides a laptop, monitor, and a one-time $500 stipend for home office setup.

## Security
Always use the VPN when connecting to company resources from public Wi-Fi networks.
""",
            "source": "hr/remote_work.md",
        },
        {
            "title": "Onboarding Checklist",
            "content": """# Onboarding Checklist

1. Complete HR paperwork in Workday.
2. Set up your email signature using the corporate template.
3. Schedule 1:1 meetings with your team members.
4. Review the security training module within your first week.
""",
            "source": "hr/onboarding.md",
        },
    ],
}


async def seed():
    """Seed the database with sample tenants and documents."""
    print("Seeding database...")
    async with async_session() as db:
        for tenant_data in TENANTS:
            # 1. Get or Create Tenant
            stmt = select(Tenant).where(Tenant.slug == tenant_data["slug"])
            result = await db.execute(stmt)
            tenant = result.scalar_one_or_none()

            if not tenant:
                tenant = Tenant(**tenant_data)
                db.add(tenant)
                await db.commit()
                await db.refresh(tenant)
                print(f"Created tenant: {tenant.name} (API key: {tenant.api_key})")
            else:
                print(f"Tenant exists: {tenant.name}")

            # 2. Clear existing docs (for clean state)
            await db.execute(text("DELETE FROM documents WHERE tenant_id = :tid"), {"tid": tenant.id})
            await db.commit()

            # 3. Ingest docs
            docs = DOCUMENTS.get(tenant.slug, [])
            for doc_inf in docs:
                await ingest_document(
                    db, tenant.id, doc_inf["title"], doc_inf["content"], doc_inf["source"]
                )
                print(f"  Ingested: {doc_inf['title']}")

    print("Seed complete.")


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    except Exception as e:
        print(f"Error seeding database: {e}")
        sys.exit(1)
