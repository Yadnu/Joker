# Latency Topography

Latency measurements (milliseconds) recorded by `joker/latency.py` at session end.
Each row represents one session's data for one pipeline stage.

## Stage definitions

| Stage | What is timed |
|-------|---------------|
| `suggestion` | Librarian.suggest: DB queries + model call to rank angles |
| `generation` | joker.generate: model call + candidate selection |
| `tts_first_byte` | OpenAI Realtime: session.update to first audio delta |
| `reaction_capture` | speech_started to speech_stopped window |
| `classification` | Librarian.classify: taxonomy fetch + model call |
| `scoring` | Librarian.score: model call |
| `filing` | Box upsert HTTP round-trip |

## Measurements

| date | stage | p50_ms | p95_ms | n |
|------|-------|-------:|-------:|--:|
