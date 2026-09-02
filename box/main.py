"""Box FastAPI application entry point."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env from the project root so DATABASE_URL and OPENAI_API_KEY are
# available whether the server is started with --env-file or not.
load_dotenv(Path(__file__).parents[1] / ".env", override=True)

from box.router import router  # noqa: E402
from joker.realtime import router as voice_router  # noqa: E402
from joker.router import router as joker_router  # noqa: E402

app = FastAPI(title="Jokebox")

# Allow the Next.js viewer (any localhost port) and any dev origin to read the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(voice_router)
app.include_router(joker_router)
