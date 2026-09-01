"""Box FastAPI application entry point."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

# Load .env from the project root so DATABASE_URL and OPENAI_API_KEY are
# available whether the server is started with --env-file or not.
load_dotenv(Path(__file__).parents[1] / ".env", override=True)

from box.router import router  # noqa: E402

app = FastAPI(title="Jokebox")
app.include_router(router)
