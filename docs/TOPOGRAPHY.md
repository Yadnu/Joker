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
| 2026-09-02 | suggestion | 7600 | 7600 | 1 |
| 2026-09-02 | generation | 3288 | 4768 | 6 |
| 2026-09-02 | suggestion | 5933 | 5933 | 1 |
| 2026-09-02 | generation | 1652 | 2158 | 6 |
| 2026-09-02 | suggestion | 7106 | 7106 | 1 |
| 2026-09-02 | generation | 1845 | 2940 | 5 |
| 2026-09-02 | suggestion | 4963 | 4963 | 1 |
| 2026-09-02 | generation | 1894 | 2641 | 5 |
| 2026-09-02 | suggestion | 5368 | 5368 | 1 |
| 2026-09-02 | generation | 1653 | 2093 | 6 |
| 2026-09-02 | suggestion | 7497 | 7497 | 1 |
| 2026-09-02 | generation | 1652 | 2702 | 5 |
| 2026-09-02 | suggestion | 4897 | 4897 | 1 |
| 2026-09-02 | generation | 1603 | 2006 | 5 |
| 2026-09-02 | suggestion | 7672 | 7672 | 1 |
| 2026-09-02 | generation | 1893 | 1996 | 5 |
| 2026-09-02 | suggestion | 10214 | 10214 | 1 |
| 2026-09-02 | generation | 1903 | 2246 | 6 |
| 2026-09-02 | suggestion | 6535 | 6535 | 1 |
| 2026-09-02 | generation | 1884 | 2268 | 6 |
| 2026-09-02 | suggestion | 4980 | 4980 | 1 |
| 2026-09-02 | generation | 1481 | 1665 | 5 |
| 2026-09-02 | suggestion | 5089 | 5089 | 1 |
| 2026-09-02 | generation | 1822 | 2252 | 5 |
| 2026-09-02 | suggestion | 7973 | 7973 | 1 |
| 2026-09-02 | generation | 2485 | 5871 | 5 |
| 2026-09-02 | suggestion | 5539 | 5539 | 1 |
| 2026-09-02 | generation | 1602 | 1908 | 6 |
| 2026-09-02 | suggestion | 5133 | 5133 | 1 |
| 2026-09-02 | generation | 1574 | 1760 | 5 |
| 2026-09-02 | suggestion | 7270 | 7270 | 1 |
| 2026-09-02 | generation | 1630 | 1765 | 5 |
| 2026-09-02 | suggestion | 7305 | 7305 | 1 |
| 2026-09-02 | generation | 1805 | 2271 | 5 |
| 2026-09-02 | suggestion | 8832 | 8832 | 1 |
| 2026-09-02 | generation | 1802 | 2401 | 6 |
| 2026-09-02 | suggestion | 6719 | 6719 | 1 |
| 2026-09-02 | generation | 1551 | 1613 | 5 |
| 2026-09-02 | suggestion | 5317 | 6288 | 5 |
| 2026-09-02 | generation | 1844 | 12552 | 10 |
| 2026-09-02 | tts_first_byte | 0 | 0 | 6 |
| 2026-09-02 | reaction_capture | 0 | 0 | 5 |
| 2026-09-02 | classification | 7370 | 7875 | 4 |
| 2026-09-02 | scoring | 1272 | 1677 | 4 |
| 2026-09-02 | filing | 2382 | 2454 | 4 |
| 2026-09-02 | suggestion | 5208 | 5316 | 2 |
| 2026-09-02 | generation | 1685 | 1946 | 7 |
| 2026-09-02 | tts_first_byte | 0 | 0 | 2 |
| 2026-09-02 | reaction_capture | 0 | 0 | 1 |
| 2026-09-02 | classification | 7586 | 7586 | 1 |
| 2026-09-02 | scoring | 1235 | 1235 | 1 |
| 2026-09-02 | filing | 2395 | 2395 | 1 |
| 2026-09-02 | suggestion | 5280 | 5280 | 1 |
| 2026-09-02 | generation | 1522 | 1917 | 5 |
| 2026-09-02 | tts_first_byte | 0 | 0 | 1 |
| 2026-09-02 | suggestion | 4808 | 5430 | 3 |
| 2026-09-02 | generation | 1256 | 1555 | 7 |
| 2026-09-02 | tts_first_byte | 0 | 0 | 7 |
| 2026-09-02 | reaction_capture | 0 | 0 | 6 |
| 2026-09-02 | classification | 12574 | 15471 | 3 |
| 2026-09-02 | scoring | 1220 | 1540 | 3 |
| 2026-09-02 | filing | 2562 | 2564 | 3 |
| 2026-09-02 | suggestion | 6237 | 6237 | 1 |
| 2026-09-02 | generation | 1227 | 1266 | 5 |
| 2026-09-02 | tts_first_byte | 0 | 0 | 1 |
| 2026-09-02 | suggestion | 7356 | 7356 | 1 |
| 2026-09-02 | generation | 1500 | 2597 | 5 |
| 2026-09-02 | tts_first_byte | 0 | 0 | 1 |
| 2026-09-02 | suggestion | 5035 | 7374 | 4 |
| 2026-09-02 | generation | 1422 | 1743 | 8 |
| 2026-09-02 | tts_first_byte | 0 | 0 | 10 |
| 2026-09-02 | reaction_capture | 0 | 0 | 9 |
| 2026-09-02 | classification | 7503 | 10035 | 5 |
| 2026-09-02 | scoring | 1101 | 1328 | 5 |
| 2026-09-02 | filing | 2284 | 2394 | 4 |
| 2026-09-02 | suggestion | 5953 | 7087 | 4 |
| 2026-09-02 | generation | 1235 | 1870 | 9 |
| 2026-09-02 | tts_first_byte | 0 | 0 | 8 |
| 2026-09-02 | reaction_capture | 0 | 0 | 7 |
| 2026-09-02 | classification | 8245 | 11569 | 6 |
| 2026-09-02 | scoring | 1395 | 1968 | 6 |
| 2026-09-02 | filing | 2366 | 2862 | 4 |
| 2026-09-02 | suggestion | 6752 | 6752 | 1 |
| 2026-09-02 | generation | 1256 | 1459 | 5 |
| 2026-09-02 | tts_first_byte | 0 | 0 | 1 |
