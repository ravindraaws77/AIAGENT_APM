"""Seed realistic demo data into your real sandbox Gmail + Calendar
account, so you have something worth asking the dashboard about instead
of an empty inbox.

This is a one-off setup utility, not part of the agent: it calls
GmailTool.send_email / CalendarTool.create_event directly with
dry_run=False, deliberately bypassing the human-approval interrupt --
that gate exists to protect a real customer's inbox from an agent acting
on its own, which doesn't apply here since you are the one asking for
this data to be created, in your own test account, as fixtures for the
agent to later read and reason about.

Six emails are sent (to yourself, with a contact email address of your
choosing embedded in the body as "the customer" so the reasoner has a
real, deliverable address to work with) covering five categories on
purpose:

  order-401, order-402, order-403   shipment_delay (same pattern, three
                                     times, so the History table's
                                     color-coding by category has a
                                     genuine repeat to make obvious)
  order-404                         missing_information (no contact
                                     info anywhere -- the agent should
                                     say so rather than invent one)
  order-405                         renewal_reminder (a real contact,
                                     so the agent can propose creating a
                                     calendar event)
  order-406                         customer_inquiry (a question, no
                                     delay -- for category variety)

Two Calendar events are also created, so the Calendar read path has
something to find too.

Setup: same as scripts/gmail_demo.py / calendar_demo.py -- Google OAuth
configured in .env, ideally against your sandbox account.

Usage:
  python scripts/seed_demo_data.py your-personal-address@example.com

Then try asking the dashboard things like:
  "chase up order 401"
  "what's going on with order 404"
  "check the Acme renewal for order 405"
"""

from __future__ import annotations

import argparse
import sys

from apm.config import load_settings
from apm.state.store import StateStore
from apm.tools.google_auth import build_gmail_and_calendar_tools

EMAILS = [
    {
        "order_id": "401",
        "subject": "Order #401 - Shipment Delayed",
        "body": (
            "Hi,\n\nUnfortunately order #401 is delayed by 5 days due to an "
            "unexpected issue with one of our suppliers. The customer's "
            "email on file is {contact}.\n\nPlease advise on next steps."
        ),
    },
    {
        "order_id": "402",
        "subject": "Order #402 - Shipment Delayed",
        "body": (
            "Hi,\n\nOrder #402 is also delayed, again due to the same "
            "supplier issue affecting recent shipments. Customer contact: "
            "{contact}.\n\nThis is the second order hitting this problem "
            "this week."
        ),
    },
    {
        "order_id": "403",
        "subject": "Order #403 - Shipment Delayed",
        "body": (
            "Hi,\n\nA third order, #403, is delayed by the same supplier "
            "issue as #401 and #402. Customer contact: {contact}.\n\nWe "
            "should probably look into why this keeps happening."
        ),
    },
    {
        "order_id": "404",
        "subject": "Order #404 - Customer asking about status",
        "body": (
            "Hi,\n\nWe got an inbound asking when order #404 will ship. "
            "No delay has actually been logged for this one, and I don't "
            "have the customer's contact info handy in this note -- "
            "someone will need to look that up separately."
        ),
    },
    {
        "order_id": "405",
        "subject": "Order #405 - Annual renewal coming up",
        "body": (
            "Hi,\n\nThe annual subscription for order #405 renews in 10 "
            "days. Customer contact: {contact}. We should probably get a "
            "renewal call on the calendar before then."
        ),
    },
    {
        "order_id": "406",
        "subject": "Order #406 - Question about invoice",
        "body": (
            "Hi,\n\nCustomer contact {contact} asked a quick question "
            "about a line item on their invoice for order #406. Nothing "
            "urgent, just wanted it on record."
        ),
    },
]

CALENDAR_EVENTS = [
    {
        "title": "Renewal call - Acme Corp",
        "start": "2026-09-15T15:00:00Z",
        "end": "2026-09-15T15:30:00Z",
    },
    {
        "title": "Contract review - Globex",
        "start": "2026-09-18T10:00:00Z",
        "end": "2026-09-18T10:45:00Z",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "contact_email",
        help="A real email address you control, used as 'the customer' contact embedded in seed email bodies "
        "(e.g. your personal address) -- never a placeholder domain like example.com, which the agent's "
        "send guard refuses outright.",
    )
    args = parser.parse_args()

    if args.contact_email.split("@")[-1].lower() in {"example.com", "example.net", "example.org", "test", "invalid"}:
        print("Refusing: that looks like a placeholder domain, not a real address you control.")
        sys.exit(1)

    settings = load_settings()
    store = StateStore()
    gmail_tool, calendar_tool = build_gmail_and_calendar_tools(store, settings)

    if not gmail_tool.health_check():
        print("Gmail connector health check failed -- check your .env and OAuth setup.")
        sys.exit(1)

    print("Sending seed emails...\n")
    for email in EMAILS:
        body = email["body"].format(contact=args.contact_email)
        result = gmail_tool.send_email(
            process_id="seed-demo-data",
            to=args.contact_email,
            subject=email["subject"],
            body=body,
            dry_run=False,
        )
        print(f"  order-{email['order_id']}: {result.description}")

    print("\nCreating seed calendar events...\n")
    for event in CALENDAR_EVENTS:
        result = calendar_tool.create_event(
            process_id="seed-demo-data",
            title=event["title"],
            start=event["start"],
            end=event["end"],
            dry_run=False,
        )
        print(f"  {result.description}")

    print(
        "\nDone. Emails land in your OWN inbox (self-sent) -- give Gmail a "
        "minute to index them before searching.\n\n"
        "Try asking the dashboard (http://localhost:8080):\n"
        '  "chase up order 401"\n'
        '  "what\'s going on with order 402"\n'
        '  "any update on order 403"   (three in a row -> same category color)\n'
        '  "what\'s happening with order 404"   (no contact info -> agent should say so)\n'
        '  "check the renewal for order 405"\n'
        '  "anything on order 406"\n'
    )


if __name__ == "__main__":
    main()
