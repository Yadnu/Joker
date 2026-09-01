#!/usr/bin/env python
"""seed.py — load sample jokes into a running Jokebox instance.

Creates one account, files a fully-compliant multi-level tree, and
deliberately leaves one file (DarkHumor > Absurdist > Existential) with a
single joke so that GET /compliance reports a real violation on a fresh install.

Usage:
    python scripts/seed.py                     # http://127.0.0.1:8000
    python scripts/seed.py http://other:8000   # custom host
"""

from __future__ import annotations

import sys
import textwrap

try:
    import httpx
except ImportError:
    sys.exit("httpx is required: pip install httpx")

BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def upsert(client: httpx.Client, api_key: str, cabinet: str, drawer: str,
           file: str, category: str, joke_text: str, score: int,
           user_reaction: str, position: int, provenance_model: str = "gpt-4o") -> str:
    payload = {
        "cabinet": cabinet,
        "drawer": drawer,
        "file": file,
        "joke": {
            "prompt_responses": [
                {"role": "system", "content": "You are a stand-up comedian."},
                {"role": "user", "content": f"Tell me a {category.lower()} joke about {file.lower()}."},
                {"role": "assistant", "content": joke_text},
            ],
            "joke_text": joke_text,
            "user_reaction": user_reaction,
            "score": score,
            "category": category,
            "metadata": {
                "topic": file.lower(),
                "style": "one-liner",
                "length": "short",
                "sensitivity_flags": [],
            },
            "user_context": {
                "energy": "dry",
                "humor_preferences": ["observational"],
            },
            "attribution": {
                "joker": "seed-script",
                "account": "seed",
            },
            "provenance": {
                "source": "curated",
                "model": provenance_model,
                "prompt": f"Tell me a {category.lower()} joke about {file.lower()}.",
                "selection_rationale": "Hand-picked seed example.",
            },
            "set_id": {"set": "seed-set", "position": position},
        },
    }
    r = client.put(
        "/box/upsert",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    r.raise_for_status()
    return r.json()["joke_id"]


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=15) as client:
        # ── Create seed account ────────────────────────────────────────────────
        r = client.post("/accounts", json={"name": "seed-account"})
        if r.status_code == 409:
            sys.exit(
                "Account 'seed-account' already exists.  "
                "Run against a fresh database or delete the account first."
            )
        r.raise_for_status()
        api_key = r.json()["api_key"]
        acct_id = r.json()["id"]
        print(f"Account created: id={acct_id}")
        print(f"API key (save this): {api_key}")
        print()

        jokes: list[tuple] = [
            # (cabinet, drawer, file, category, joke_text, score, user_reaction, position)

            # ── Observational / Everyday Life ──────────────────────────────────
            ("Observational", "Everyday Life", "Work", "Observational",
             "Why do programmers prefer dark mode? Because light attracts bugs.", 8,
             "Ha! That's actually true.", 1),
            ("Observational", "Everyday Life", "Work", "Observational",
             "I told my boss I needed a raise. He said, 'Consider it done.' I'm still considering.", 7,
             "Laughed and nodded.", 2),
            ("Observational", "Everyday Life", "Technology", "Observational",
             "My WiFi password is 'incorrect'. So when guests ask, I say it's 'incorrect'.", 9,
             "Audible groan then a laugh.", 1),
            ("Observational", "Everyday Life", "Technology", "Observational",
             "I asked Siri why I'm still single. She opened Tinder.", 8,
             "Surprised laugh.", 2),

            # ── Observational / Social ──────────────────────────────────────────
            ("Observational", "Social", "Restaurants", "Observational",
             "I hate when restaurants ask 'how's your food?' while my mouth is full. It's a trap.", 7,
             "Pointed at their mouth and nodded.", 1),
            ("Observational", "Social", "Restaurants", "Observational",
             "I ordered a salad and felt judged by everyone who ordered a burger.", 6,
             "Chuckled.", 2),
            ("Observational", "Social", "Relationships", "Observational",
             "My wife said I never listen. At least that's what I think she said.", 8,
             "His partner threw a napkin at him.", 1),
            ("Observational", "Social", "Relationships", "Observational",
             "We're so compatible. She finishes my sentences and I finish her patience.", 7,
             "Knowing laugh from the couples in the room.", 2),

            # ── Wordplay / Puns ──────────────────────────────────────────────────
            ("Wordplay", "Puns", "Animals", "Wordplay",
             "I'm reading a book about anti-gravity. It's impossible to put down.", 7,
             "Booed then clapped.", 1),
            ("Wordplay", "Puns", "Animals", "Wordplay",
             "Did you hear about the cat who swallowed a ball of wool? She had mittens.", 8,
             "Genuine laugh.", 2),
            ("Wordplay", "Puns", "Food", "Wordplay",
             "I used to hate facial hair but then it grew on me.", 7,
             "Groan and a laugh.", 1),
            ("Wordplay", "Puns", "Food", "Wordplay",
             "I'm on a seafood diet. I see food and I eat it.", 6,
             "Classic groan.", 2),

            # ── Wordplay / Riddles ──────────────────────────────────────────────
            ("Wordplay", "Riddles", "Classic Riddles", "Wordplay",
             "What do you call a fake noodle? An impasta.", 7,
             "Groan then laughter.", 1),
            ("Wordplay", "Riddles", "Classic Riddles", "Wordplay",
             "Why don't scientists trust atoms? Because they make up everything.", 8,
             "Big laugh.", 2),
            ("Wordplay", "Riddles", "Knock Knock", "Wordplay",
             "Knock knock. Who's there? Interrupting cow. Interrupting cow wh— MOO!", 9,
             "Laughed so hard they spilled their drink.", 1),
            ("Wordplay", "Riddles", "Knock Knock", "Wordplay",
             "Knock knock. Who's there? Opportunity. But opportunity only knocks once.", 7,
             "Groan. Then thought about it. Then laughed.", 2),

            # ── DarkHumor / Satire (compliant) ──────────────────────────────────
            ("DarkHumor", "Satire", "Workplace", "DarkHumor",
             "Our company just got acquired. The new owners value our employees. They told us that right before the layoffs.", 8,
             "Uncomfortable laugh from the tech workers.", 1),
            ("DarkHumor", "Satire", "Workplace", "DarkHumor",
             "We have a great work-life balance. I'm alive at work and dead at home.", 7,
             "Dark laugh.", 2),
            ("DarkHumor", "Satire", "Social", "DarkHumor",
             "Social media lets you argue with strangers about things that don't matter. It's basically free therapy that makes everything worse.", 8,
             "Laughed. Then looked at their phone.", 1),
            ("DarkHumor", "Satire", "Social", "DarkHumor",
             "Influencers are just people who get paid to make you feel bad about your life in a fun way.", 7,
             "Tired laugh.", 2),

            # ── DarkHumor / Absurdist / Surreal (compliant) ─────────────────────
            ("DarkHumor", "Absurdist", "Surreal", "DarkHumor",
             "I told a joke in an empty room. It laughed. We're best friends now.", 7,
             "Confused pause then laughter.", 1),
            ("DarkHumor", "Absurdist", "Surreal", "DarkHumor",
             "A horse walks into a bar. Several patrons leave, recognising the potential danger.", 8,
             "Slow clap.", 2),
        ]

        # ── DELIBERATE VIOLATION: one joke only in DarkHumor > Absurdist > Existential
        violation_joke = (
            "DarkHumor", "Absurdist", "Existential", "DarkHumor",
            "I asked myself what the point of it all was. I'm still on hold.", 8,
            "Long silence. Then a very quiet laugh.", 99,
        )

        pos = 1
        for cab, drw, fil, cat, text, score, reaction, p in jokes:
            upsert(client, api_key, cab, drw, fil, cat, text, score, reaction, p)
            pos += 1

        # File the violation (single joke)
        cab, drw, fil, cat, text, score, reaction, p = violation_joke
        violation_id = upsert(client, api_key, cab, drw, fil, cat, text, score, reaction, p)

        print(f"Filed {len(jokes)} compliant jokes across 3 cabinets, 6 drawers, 11 files.")
        print(f"Filed 1 violation joke (id={violation_id}): DarkHumor > Absurdist > Existential has 1 joke.")
        print()
        print("Check compliance:")
        print(f"  curl {BASE_URL}/compliance")
        print()
        print("Read the violation file:")
        print(f"  curl '{BASE_URL}/box/DarkHumor/Absurdist/Existential'")


if __name__ == "__main__":
    main()
