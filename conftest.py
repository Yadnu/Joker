"""Avoid constructing OpenAI clients against a missing key during imports."""

from __future__ import annotations

import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-used")
