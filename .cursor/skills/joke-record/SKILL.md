---
name: joke-record
description: Use when constructing, reading, serializing, or validating a joke record anywhere in the system, in Python or in TypeScript.
version: "2.0.0"
---

# Joke Record

The canonical joke record is defined in `box/schema/records.py`. Field names are
fixed and graded against a written spec. Do not rename, pluralize, or paraphrase
them in Python or TypeScript.

## Fields (exact names)

| Field | Type | Notes |
|-------|------|-------|
| `prompt_responses` | ordered list of `{role, content}` | Turn-by-turn exchange that produced the joke |
| `joke_text` | `str` | Full joke as delivered; used for search |
| `user_reaction` | `str` | What the user said after the punchline; not part of the joke |
| `score` | `int` 0–10 | Landing score |
| `category` | `str` | Genre assigned by the Librarian; must equal the file label; never `"General"` |
| `metadata` | `{topic, style, length, sensitivity_flags}` | `sensitivity_flags` is `list[HumorStyle]` |
| `user_context` | `UserContext` object (see below) | Structured per-session listener snapshot; all fields optional |
| `attribution` | `{joker, account}` | Which Joker and which account filed this |
| `provenance` | `{source, model, prompt, selection_rationale}` | `source` is `generated` or `curated`; all four sub-fields required |
| `set_id` | `{set, position}` | Which set and what position in it |

## UserContext shape

All fields are optional. A session with only one field populated is valid.

```
age_band          "under_25" | "25_40" | "40_60" | "over_60"
region            str  — coarse locale, e.g. "US West", "UK". NOT a city.
occupation_field  "tech" | "healthcare" | "education" | "trades" |
                  "finance" | "student" | "retired" | "other"
humor_preferences list[HumorStyle]  — styles the listener enjoys
humor_avoid       list[HumorStyle]  — HARD CONSTRAINT; never a soft preference
energy            "warm" | "dry" | "rowdy" | "reserved"
first_time        bool
session_notes     str  — one short free-text line
```

**Never store:** name, date of birth, exact age, email, employer, city, or any
other identifying value. See `records.py` module docstring and DECISIONS.md.

## HumorStyle vocabulary (shared by sensitivity_flags, humor_preferences, humor_avoid)

```
wordplay  observational  absurdist  deadpan
dark      physical       self_deprecating  topical
```

These three lists share one enum so the Audience Categorizer can map listener
traits onto sensitivity flags without translation.

## Worked example

```json
{
  "prompt_responses": [
    {"role": "system", "content": "You are a stand-up comedian specializing in observational humour."},
    {"role": "user",   "content": "Tell me a short joke about airport security."},
    {"role": "assistant", "content": "I told the TSA agent I packed my own bags. He said, 'That's great—now unpack them.'"}
  ],
  "joke_text": "I told the TSA agent I packed my own bags. He said, 'That's great—now unpack them.'",
  "user_reaction": "Ha! That's exactly what happened to me last Tuesday.",
  "score": 8,
  "category": "Observational",
  "metadata": {
    "topic": "airport security",
    "style": "one-liner",
    "length": "short",
    "sensitivity_flags": []
  },
  "user_context": {
    "age_band": "25_40",
    "region": "US West",
    "occupation_field": "tech",
    "humor_preferences": ["observational", "deadpan"],
    "humor_avoid": ["dark"],
    "energy": "dry",
    "first_time": false,
    "session_notes": "Responded well to relatable inconvenience humour."
  },
  "attribution": {
    "joker": "joker-v1",
    "account": "acct_7f3a92"
  },
  "provenance": {
    "source": "generated",
    "model": "gpt-4o",
    "prompt": "Tell me a short joke about airport security.",
    "selection_rationale": "Highest score among three candidates; best punchline timing for short-form delivery."
  },
  "set_id": {
    "set": "set_travel_2026_08_31",
    "position": 3
  }
}
```
