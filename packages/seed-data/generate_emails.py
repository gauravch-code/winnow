"""Generate 200 deterministic synthetic emails for the demo.

Run once (or after schema changes) with:
    uv run python packages/seed-data/generate_emails.py

Deterministic — same seed always produces the same 200 emails, so the
committed JSON files change only when this script changes. Templates
per category strike a balance between realism (varied enough to read
like a real inbox) and repo hygiene (no accidental PII, no external API).

This script is separate from ``generate.py`` (the tier-2 LLM fixture
generator, Step 6) — that one calls Anthropic and costs money; this one
runs offline and is free.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from winnow_seed_data.seed_email_schema import Category, Lane, SeedEmail

SEED = 20260716  # bump if you want a different-but-still-stable corpus
NOW = datetime(2026, 7, 16, 9, 0, 0, tzinfo=timezone.utc)

OUT_DIR = Path(__file__).parent / "emails"
ME = "me@winnow.dev"

# Category distribution roughly matches a working inbox: heavy on newsletters
# and notifications, moderate on work threads, light on personal + receipts.
DISTRIBUTION: dict[Category, int] = {
    "newsletter": 40,
    "notification": 30,
    "work": 45,
    "personal": 25,
    "calendar": 20,
    "receipt": 25,
    "spam": 15,
}
assert sum(DISTRIBUTION.values()) == 200

# --- template banks ---------------------------------------------------------
# Each tuple: (subject_template, body_template, sender_pool, ground_truth_lane)
# {var} placeholders are filled from PEOPLE, COMPANIES, PROJECTS.

PEOPLE = [
    ("Priya Shah", "priya"), ("Jamal Wright", "jamal"), ("Elena Rossi", "elena"),
    ("Kenji Ito", "kenji"), ("Nadia Farouk", "nadia"), ("Diego Alvarez", "diego"),
    ("Sasha Kim", "sasha"), ("Marcus Bell", "marcus"), ("Yara Haddad", "yara"),
    ("Tomas Brandt", "tomas"),
]
COMPANIES = ["acme", "northwind", "contoso", "globex", "initech", "umbrella"]
NEWSLETTERS = [
    ("The Pragmatic Engineer", "newsletter@pragmaticengineer.com", "pragmaticengineer.com"),
    ("Stratechery", "ben@stratechery.com", "stratechery.com"),
    ("Lenny's Newsletter", "hi@lennysnewsletter.com", "lennysnewsletter.com"),
    ("Import AI", "jack@importai.substack.com", "substack.com"),
    ("Morning Brew", "crew@morningbrew.com", "morningbrew.com"),
]
NOTIFICATION_DOMAINS = [
    ("GitHub", "noreply@github.com", "github.com"),
    ("Slack", "notifications@slack.com", "slack.com"),
    ("Linear", "notifications@linear.app", "linear.app"),
    ("Google Drive", "drive-shares-noreply@google.com", "google.com"),
    ("Notion", "team@mail.notion.so", "notion.so"),
]
RECEIPTS = [
    ("Stripe", "receipts@stripe.com", "stripe.com"),
    ("Uber", "receipts@uber.com", "uber.com"),
    ("Amazon", "auto-confirm@amazon.com", "amazon.com"),
    ("Airbnb", "automated@airbnb.com", "airbnb.com"),
    ("DoorDash", "no-reply@doordash.com", "doordash.com"),
]
SPAM_SENDERS = [
    ("Crypto Winners", "winner@lucky-token-airdrop.xyz", "lucky-token-airdrop.xyz"),
    ("SEO Growth", "leads@growth-hackers-pro.biz", "growth-hackers-pro.biz"),
    ("HR at BigCo", "recruiter@totally-real-hr.top", "totally-real-hr.top"),
]
PROJECTS = ["Q3 planning", "auth migration", "onboarding revamp", "billing v2", "search reindex"]


def _rng() -> random.Random:
    return random.Random(SEED)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _make(
    rng: random.Random,
    idx: int,
    category: Category,
    lane: Lane,
    sender_name: str | None,
    sender_email: str,
    sender_domain: str,
    subject: str,
    body: str,
    thread_depth: int = 1,
    has_unsubscribe: bool = False,
    is_reply: bool = False,
    cc: list[str] | None = None,
) -> SeedEmail:
    received = NOW - timedelta(minutes=rng.randint(5, 60 * 24 * 14))
    snippet = body.strip().splitlines()[0][:120]
    return SeedEmail(
        id=f"seed_{idx:03d}",
        sender_email=sender_email,
        sender_name=sender_name,
        sender_domain=sender_domain,
        recipients={"to": [ME], "cc": cc or [], "bcc": []},
        subject=subject,
        body_text=body,
        snippet=snippet,
        received_at=received,
        thread_depth=thread_depth,
        has_unsubscribe=has_unsubscribe,
        is_reply=is_reply,
        category=category,
        ground_truth_lane=lane,
    )


# --- category generators ---------------------------------------------------


def gen_newsletter(rng: random.Random, idx: int) -> SeedEmail:
    name, addr, domain = rng.choice(NEWSLETTERS)
    topics = [
        "why one-on-ones are broken",
        "the case for tiny teams",
        "vector DBs, one year later",
        "what makes a great PM",
        "the incident that changed our on-call",
    ]
    topic = rng.choice(topics)
    subject = f"[{name}] {topic}"
    body = (
        f"This week's issue: {topic}.\n\n"
        "3 things worth your time, 2 charts, 1 recommendation.\n\n"
        "Read the full issue online. Unsubscribe at any time."
    )
    return _make(
        rng, idx, "newsletter", "informational",
        name, addr, domain, subject, body,
        has_unsubscribe=True,
    )


def gen_notification(rng: random.Random, idx: int) -> SeedEmail:
    name, addr, domain = rng.choice(NOTIFICATION_DOMAINS)
    if "github" in domain:
        proj = rng.choice(PROJECTS).replace(" ", "-")
        pr_num = rng.randint(100, 999)
        subject = f"[{proj}] Pull request #{pr_num} was merged"
        body = f"{rng.choice(PEOPLE)[0]} merged pull request #{pr_num} into main.\n\nView on GitHub."
    elif "slack" in domain:
        person = rng.choice(PEOPLE)[0]
        subject = f"New message from {person} in #eng-general"
        body = f"{person}: quick q — got a sec to look at the deploy?\n\nReply in Slack."
    elif "linear" in domain:
        subject = f"[{rng.choice(PROJECTS)}] Issue assigned to you"
        body = "You've been assigned a new issue. View in Linear."
    else:
        subject = f"{rng.choice(PEOPLE)[0]} shared a document with you"
        body = "A document has been shared. Click to view."
    return _make(
        rng, idx, "notification", "informational",
        name, addr, domain, subject, body,
        has_unsubscribe=True,
    )


def gen_work(rng: random.Random, idx: int) -> SeedEmail:
    sender_name, handle = rng.choice(PEOPLE)
    company = rng.choice(COMPANIES)
    domain = f"{company}.com"
    email = f"{handle}@{domain}"
    project = rng.choice(PROJECTS)
    templates = [
        (
            f"Re: {project} — comments by Thursday?",
            f"Hey — could you leave your comments on the {project} doc by end of Thursday? "
            "I want to circulate the revised draft on Friday morning.\n\nThanks!",
            "needs_you",
            2,
            True,
        ),
        (
            f"Quick question about {project}",
            f"Do you have 15 min today to walk me through the {project} rollout plan? "
            "I want to make sure I understand the phase 2 dependencies.",
            "needs_you",
            1,
            False,
        ),
        (
            f"{project}: meeting notes",
            f"Notes from the {project} sync are attached. No action items for you — "
            "sharing for visibility.",
            "informational",
            1,
            False,
        ),
        (
            f"FYI: {project} weekly digest",
            f"Weekly rollup for {project}. Nothing needs your input this week.",
            "informational",
            1,
            False,
        ),
        (
            f"Re: {project} — approved",
            f"Approved. Ship it whenever you're ready.",
            "informational",
            3,
            True,
        ),
    ]
    subject, body, lane, depth, is_reply = rng.choice(templates)
    cc = []
    if rng.random() < 0.3:
        other = rng.choice(PEOPLE)
        cc = [f"{other[1]}@{domain}"]
    return _make(
        rng, idx, "work", lane,
        sender_name, email, domain, subject, body,
        thread_depth=depth, is_reply=is_reply, cc=cc,
    )


def gen_personal(rng: random.Random, idx: int) -> SeedEmail:
    sender_name, handle = rng.choice(PEOPLE)
    domain = rng.choice(["gmail.com", "protonmail.com", "hey.com"])
    email = f"{handle}@{domain}"
    templates = [
        (
            "dinner Saturday?",
            "hey! a few of us are getting together saturday around 7. you in?\n\nno pressure, just let me know",
            "needs_you", 1, False,
        ),
        (
            "Re: hiking next month",
            "yeah that trail works! let's do the 8am start so we're back before it gets hot.",
            "needs_you", 2, True,
        ),
        (
            "photos from last weekend",
            "finally uploaded them! link in signature. no rush to look.",
            "informational", 1, False,
        ),
        (
            "did you see this?",
            "sent you an article, curious what you think when you get a chance",
            "needs_you", 1, False,
        ),
    ]
    subject, body, lane, depth, is_reply = rng.choice(templates)
    return _make(
        rng, idx, "personal", lane,
        sender_name, email, domain, subject, body,
        thread_depth=depth, is_reply=is_reply,
    )


def gen_calendar(rng: random.Random, idx: int) -> SeedEmail:
    person = rng.choice(PEOPLE)[0]
    project = rng.choice(PROJECTS)
    templates = [
        (
            f"Invitation: {project} sync @ Thu 2:00 PM",
            f"{person} has invited you to '{project} sync'. Accept, Decline, or Maybe.",
            "informational",
        ),
        (
            f"Updated: 1:1 with {person}",
            f"The event '1:1 with {person}' has been moved to next Tuesday at 3 PM.",
            "informational",
        ),
        (
            "Reminder: All-hands @ 10:00 AM tomorrow",
            "Reminder: you have an event 'All-hands' tomorrow at 10:00 AM.",
            "informational",
        ),
    ]
    subject, body, lane = rng.choice(templates)
    return _make(
        rng, idx, "calendar", lane,
        "Google Calendar", "calendar-notification@google.com", "google.com",
        subject, body,
    )


def gen_receipt(rng: random.Random, idx: int) -> SeedEmail:
    name, addr, domain = rng.choice(RECEIPTS)
    amount = round(rng.uniform(4.50, 250.00), 2)
    templates = {
        "Stripe": (f"Receipt from Acme Co #{rng.randint(10000, 99999)}",
                   f"Amount charged: ${amount}\nCard ending 4242."),
        "Uber": (f"Your Wednesday morning trip with Uber",
                 f"Trip total: ${amount}\nThanks for riding."),
        "Amazon": (f"Your Amazon.com order of item(s)",
                   f"Order total: ${amount}\nArriving Friday."),
        "Airbnb": (f"Reservation confirmed: Portland",
                   f"Total: ${amount}\nCheck-in Aug 3."),
        "DoorDash": (f"Order confirmed from The Corner Bistro",
                     f"Total: ${amount}\nEstimated arrival 25-35 min."),
    }
    subject, body = templates[name]
    return _make(
        rng, idx, "receipt", "hidden",
        name, addr, domain, subject, body,
        has_unsubscribe=True,
    )


def gen_spam(rng: random.Random, idx: int) -> SeedEmail:
    name, addr, domain = rng.choice(SPAM_SENDERS)
    templates = [
        ("You've been selected — claim your $500 airdrop",
         "Congratulations! You qualify for our exclusive token distribution. Click here to claim before Friday."),
        ("Boost your SEO by 300% — free consultation",
         "Our proven system helps businesses like yours dominate Google. Reply YES for a free 15-minute call."),
        ("Urgent: your account will be suspended",
         "We noticed unusual activity. Verify your identity within 24 hours or lose access."),
    ]
    subject, body = rng.choice(templates)
    return _make(
        rng, idx, "spam", "hidden",
        name, addr, domain, subject, body,
        has_unsubscribe=False,
    )


GENERATORS = {
    "newsletter": gen_newsletter,
    "notification": gen_notification,
    "work": gen_work,
    "personal": gen_personal,
    "calendar": gen_calendar,
    "receipt": gen_receipt,
    "spam": gen_spam,
}


def main() -> None:
    rng = _rng()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Wipe old files so removed IDs don't linger and confuse the loader.
    for existing in OUT_DIR.glob("seed_*.json"):
        existing.unlink()

    emails: list[SeedEmail] = []
    idx = 1
    for category, count in DISTRIBUTION.items():
        for _ in range(count):
            emails.append(GENERATORS[category](rng, idx))
            idx += 1

    # Shuffle so the ID order doesn't correlate with category — otherwise
    # the demo's "first 40" would all be newsletters.
    rng.shuffle(emails)
    # Reassign IDs after shuffle so the file names run seed_001..seed_200
    # in a well-mixed category order.
    for new_idx, email in enumerate(emails, start=1):
        emails[new_idx - 1] = email.model_copy(update={"id": f"seed_{new_idx:03d}"})

    for email in emails:
        (OUT_DIR / f"{email.id}.json").write_text(
            email.model_dump_json(indent=2), encoding="utf-8"
        )

    by_cat: dict[str, int] = {}
    by_lane: dict[str, int] = {}
    for e in emails:
        by_cat[e.category] = by_cat.get(e.category, 0) + 1
        by_lane[e.ground_truth_lane] = by_lane.get(e.ground_truth_lane, 0) + 1
    print(f"Generated {len(emails)} emails at {OUT_DIR}")
    print(f"  by category: {by_cat}")
    print(f"  by lane:     {by_lane}")


if __name__ == "__main__":
    main()
