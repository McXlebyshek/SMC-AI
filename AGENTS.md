# AGENTS.md — SMC/ICT Chart Analyzer

## Project: SMC/ICT Chart Analyzer
**Goal:** Automated financial market analysis — algorithmic SMC/ICT pattern detection (OHLCV-based) + VLM interpretation.
**Spec:** `TZ_SMC_ICT_chart_analyzer.md` | **Roadmap:** `TODO.md`
**Status:** Stages 0–2 complete (data pipeline + chart renderer). Stage 3 ready to start.

## Quick Start (Windows)
```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest tests/ -v
```

## Architecture
```
Bybit/ccxt → Data Pipeline → Chart Renderer ─┐
  [symbols.yaml]                              ├→ Orchestrator → VLM → JSON
  [db_schema.sql]                              │
  [model_config.yaml] ── RAG ── Rules Engine ─┘
```

**Hybrid approach is mandatory.** Algorithmic detector (Stage 3) finds patterns from OHLCV. VLM only interprets — never determines price levels.

## Repo Map

| Path | Purpose |
|------|---------|
| `config/symbols.yaml` | Symbols, timeframes (1W/1D/4H/1H/15m), session defs |
| `config/model_config.yaml` | VLM (Qwen3.6-35B-A3B), server opts, system prompt |
| `data/bybit_client.py` | ccxt wrapper — `BybitClient` |
| `data/fetch_history.py` | Paginated history download (1000 candle/page) + `fetch_all_symbols` |
| `data/fetch_realtime.py` | Last N candles for live analysis |
| `data/db_manager.py` | SQLAlchemy sync ORM — `DBManager` |
| `data/db_schema.sql` | Full schema: ohlcv, smc_patterns, session_results, analysis_runs |
| `render/renderer.py` | mplfinance candlestick → PNG |
| `render/chart_config.py` | Visual params (colors, background, margins) |
| `render/sessions.py` | Session zone overlays (Asian/London/NY) |
| `tests/` | pytest — mocks for API, real SQLite for DB, live-render for charts |
| `requirements.txt` | Python deps |

## Critical Gotchas

**Symbol format:** `BybitClient.fetch_ohlcv()` expects `BTC/USDT` (ccxt format with slash). Config `symbols.yaml` lists `BTCUSDT` (no slash). Convert: `symbol.replace("USDT", "/USDT")`.

**DataFrame column naming:** ccxt returns → `Open, High, Low, Close, Volume` (capitalized). DB query returns → `open, high, low, close, volume` (lowercase). Don't mix them.

**DBManager uses sync SQLAlchemy, not async.** Despite `aiosqlite` in requirements, `DBManager` uses `sqlalchemy.orm.Session` (synchronous). For async, you'd need separate wrapper.

**SQLite upsert:** Uses `INSERT OR IGNORE` (not `ON CONFLICT`). The unique index on `(symbol, timeframe, timestamp)` handles dedup. Chunk size for bulk is 500 (SQLite bind param limit is 999).

**VLM server:** `http://127.0.0.1:8000/v1` (llama.cpp + ollama-compatible endpoint). Model: `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf`. Context: 98304. Must be running before orchestration.

**No linter/formatter configured.** Just `pytest` for verification. Follow PEP 8 + type hints + docstrings.

## Development Workflow

**Stage order:** 0→10 (Stages 3+4 parallel). Each stage needs `Definition of Done` before advancing.

**For SMC algorithms (Stage 3+):** TDD is mandatory. Write `pytest` tests against hardcoded mock OHLCV candles *before* implementation. See `TODO.md` Stage 3 for file layout.

**Commits:** One atomic commit per working unit. No large feature commits.

**Branches:** No specific convention enforced. Use descriptive names.

## Testing
```powershell
# All tests
python -m pytest tests/ -v

# Single file
python -m pytest tests/test_data_pipeline.py -v

# Single test
python -m pytest tests/test_data_pipeline.py::TestFetchOHLCV::test_fetch_returns_dataframe -v
```

- `tests/test_bybit_client.py`: Mocked ccxt + live connection integration test
- `tests/test_data_pipeline.py`: Real SQLite (temp file), 589 lines — covers CRUD, filters, edge cases, duplicates
- `tests/test_fetch_history.py`: Mocked pagination, dedup, boundary filters
- `tests/test_renderer.py`: Live BTC/USDT 1D fetch → mplfinance PNG to `tests/output/` (visual inspection)

## Key Constraints
- TradingView scraping forbidden (ToS violation)
- No hardcoded API keys — use `.env` (already in `.gitignore`)
- Forex/DXY not on Bybit — need OANDA/ Twelve Data (placeholder in config)
- SMC/ICT is partially discretionary — 100% algorithmic match to manual labeling is not the goal
