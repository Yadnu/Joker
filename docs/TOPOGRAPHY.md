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

Rows tagged `placeholder` are method estimates, not live voice captures.
`joker/latency.py` appends measured rows at session end using the four-column
table below (no `source` column).

**Methodology:** CI does not run a live OpenAI Realtime session. Placeholder
p50/p95 are order-of-magnitude estimates for model and TTS hops. The
`generation` row with n=5 is **measured** from `LatencyTracker` unit samples
`(10, 20, 30, 40, 50)` ms (p50=30, p95=48), not live TTS. Replace placeholder
rows after a real `/ws/session/{id}` run flushes this file.

| date | stage | p50_ms | p95_ms | n |
|------|-------|-------:|-------:|--:|
| 2026-09-01 | suggestion | 180 | 420 | 0 |
| 2026-09-01 | generation | 900 | 2200 | 0 |
| 2026-09-01 | tts_first_byte | 250 | 600 | 0 |
| 2026-09-01 | reaction_capture | 80 | 200 | 0 |
| 2026-09-01 | classification | 700 | 1600 | 0 |
| 2026-09-01 | scoring | 220 | 480 | 0 |
| 2026-09-01 | filing | 40 | 90 | 0 |
| 2026-09-01 | generation | 30 | 48 | 5 |
| 2026-09-02 | suggestion | 7397 | 7397 | 1 |
| 2026-09-02 | generation | 26774 | 29395 | 6 |
| 2026-09-02 | suggestion | 5032 | 5032 | 1 |
| 2026-09-02 | generation | 28940 | 30818 | 6 |
| 2026-09-02 | suggestion | 5119 | 5119 | 1 |
| 2026-09-02 | generation | 29308 | 37254 | 6 |
| 2026-09-02 | suggestion | 5130 | 5130 | 1 |
| 2026-09-02 | generation | 20570 | 27967 | 6 |
| 2026-09-02 | suggestion | 6318 | 6318 | 1 |
| 2026-09-02 | generation | 29606 | 31909 | 6 |
| 2026-09-02 | suggestion | 10049 | 10049 | 1 |
| 2026-09-02 | generation | 2076 | 3572 | 5 |
