#!/usr/bin/env python3
"""
Builds data/demo/ — fixed-seed fixtures shaped like Haven Solutions, safe to
screen-record. Re-run any time; output is byte-identical (seed = 20260101).

These are INVENTED prospects, not real clients — Haven Solutions has none yet.
"""
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

SEED = 20260101
ANCHOR = date(2026, 8, 25)  # fixed "today" for the fixtures, not the real date

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "demo"

CLIENTS = [
    {
        "slug": "riverside-cafe",
        "name": "Riverside Cafe",
        "contact": "Priya Nair",
        "services": ["Landing Page / Single-Page Site", "Booking/Appointment System Integration"],
        "market": "local",
    },
    {
        "slug": "bloom-salon",
        "name": "Bloom & Co Salon",
        "contact": "Meera Suresh",
        "services": ["Full Website (up to 5 pages)", "Social Media Template Kit", "Growth Retainer (Design + Tech, ongoing)"],
        "market": "local",
    },
    {
        "slug": "whitfield-dental",
        "name": "Whitfield Dental",
        "contact": "Dr. James Whitfield",
        "services": ["Full Launch Package"],
        "market": "uk",
    },
    {
        "slug": "nomad-coworking",
        "name": "Nomad Coworking",
        "contact": "Arjun Mehta",
        "services": ["CRM Setup & Lead Automation", "Website Maintenance & Hosting"],
        "market": "local",
    },
    {
        "slug": "oakline-fitness",
        "name": "Oakline Fitness",
        "contact": "Sarah Oakes",
        "services": ["Growth Starter Bundle", "Reputation Monitoring & GBP Management"],
        "market": "uk",
    },
]

PRICE_RANGES = {
    "Landing Page / Single-Page Site": {"local": (8000, 15000, "INR"), "uk": (400, 700, "GBP")},
    "Full Website (up to 5 pages)": {"local": (20000, 40000, "INR"), "uk": (1200, 2500, "GBP")},
    "Booking/Appointment System Integration": {"local": (6000, 12000, "INR"), "uk": (350, 600, "GBP")},
    "CRM Setup & Lead Automation": {"local": (10000, 20000, "INR"), "uk": (500, 900, "GBP")},
    "Website Maintenance & Hosting": {"local": (2500, 5000, "INR"), "uk": (100, 200, "GBP")},
    "Social Media Template Kit": {"local": (6000, 12000, "INR"), "uk": (300, 600, "GBP")},
    "Growth Retainer (Design + Tech, ongoing)": {"local": (15000, 30000, "INR"), "uk": (600, 1200, "GBP")},
    "Full Launch Package": {"local": (35000, 60000, "INR"), "uk": (2000, 3500, "GBP")},
    "Growth Starter Bundle": {"local": (25000, 40000, "INR"), "uk": (1500, 2500, "GBP")},
    "Reputation Monitoring & GBP Management": {"local": (3000, 6000, "INR"), "uk": (150, 300, "GBP")},
}

SYMBOL = {"INR": "₹", "GBP": "£"}


def price_for(service: str, market: str, rng: random.Random) -> str:
    lo, hi, ccy = PRICE_RANGES[service][market]
    amount = rng.randrange(lo, hi + 1, 500 if ccy == "INR" else 50)
    return f"{SYMBOL[ccy]}{amount:,}"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def main() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    rng = random.Random(SEED)

    statuses = ["unpaid", "partial", "paid"]
    invoice_meta = {}

    for i, client in enumerate(CLIENTS):
        slug, name = client["slug"], client["name"]
        status = statuses[i % len(statuses)]
        due_offset = rng.randint(-14, 21)
        due = ANCHOR + timedelta(days=due_offset)
        service = client["services"][0]
        total = price_for(service, client["market"], rng)
        invoice_meta[slug] = {"status": status, "due": due, "total": total, "service": service}

        write(
            OUT_DIR / "Clients" / f"{slug}.md",
            f"""# {name}

Contact: {client['contact']}
Market: {client['market'].upper()}

Services engaged: {', '.join(client['services'])}

See [[{slug}-proposal]] and [[{slug}-invoice-1]].

## Notes
{name} came in via referral. {client['contact']} is the primary point of contact — keep replies short, they read on mobile.
""",
        )

        write(
            OUT_DIR / "Proposals" / f"{slug}-proposal.md",
            f"""# Proposal — {name}

Client: [[{slug}]]

Scope: {service}
Quoted: {total}

Status: sent, awaiting sign-off.
""",
        )

        write(
            OUT_DIR / "Invoices" / f"{slug}-invoice-1.md",
            f"""# Invoice — {name} #1

Client: [[{slug}]]
Service: {service}
Amount: {total}
Due: {due.isoformat()}
Status: {status}
""",
        )

    write(
        OUT_DIR / "Notes" / "follow-ups.md",
        """# Follow-ups

- [[bloom-salon]] — chase retainer sign-off, mentioned budget approval "this week" twice now.
- [[whitfield-dental]] — send the UK case-study deck before the next call, they asked for proof of quality.
- [[nomad-coworking]] — CRM automation build is scoped, waiting on their lead-source list.
""",
    )

    write(
        OUT_DIR / "Notes" / "greyb.md",
        """# GreyB

Day job. Full-time, pays the bills while Haven Solutions gets off the ground.
No client work happens on GreyB time or with GreyB resources — keep the two separate.
""",
    )

    write(
        OUT_DIR / "Research" / "uk-market-notes.md",
        """# UK Market Notes

UK SMBs expect case studies and a polished deck before they'll pay GBP rates —
see [[whitfield-dental]] and [[oakline-fitness]] for the two live UK prospects.
Local agencies quoting similar scope run £300-£500 higher than our starting
prices; room to move up once there are 2-3 UK case studies to point to.
""",
    )

    write(
        OUT_DIR / "Notes" / "pricing.md",
        "# Pricing reference\n\nSee the full catalog: [[haven-services]]\n",
    )
    shutil.copy(BASE_DIR / "haven-services.md", OUT_DIR / "Notes" / "haven-services.md")

    total_files = sum(1 for _ in OUT_DIR.rglob("*.md"))
    print(f"Wrote {total_files} demo files to {OUT_DIR} (seed={SEED})")


if __name__ == "__main__":
    main()
