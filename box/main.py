"""Box FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI

from box.router import router

app = FastAPI(title="Jokebox")
app.include_router(router)
