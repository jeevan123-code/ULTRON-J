# Phase 6 — World Events + Scheduled Briefings + Live Wiring

Status: SHIPPED on branch `phase6-world-and-briefings`.

## What Phase 6 Builds

Three sub-features layered onto the existing autonomous loop:

### 1. World-event auto-research

```
RSSSource / NewsAPISource / AlphaVantageSource
        |
        v
world_event_poller (background thread or _tick_for_test)
        |
        v
interest_matcher (interests.json overrides conversation_listener)
        |
        v
worldfeed_store (ranked, JSON-backed, MAX_BUFFER=200)
```

ULTRON's prior auto-research (Phase 2b) listened to *your* conversation
and picked topics from it. Phase 6 inverts that: it polls outside RSS
feeds and free APIs (NewsAPI, Alpha Vantage), then ranks each item by
how strongly it matches your interests.

### 2. Scheduled briefings

```
scheduled_briefings.json  <-- briefing_scheduler CRUD (cron exprs via croniter)
                                                      |
                                                      v
                                              briefing_builder.compose()
                                                      |
                          (worldfeed top-5) + (research_queue top-3) + (recent goals)
                                                      |
                                                      v
                                              briefing_delivery.deliver()
                                                      |
                                          telegram (mobile_bridge) + voice (voice_engine.tts)
```

One voice trigger or one cron fire produces a coherent "your morning"
text and pushes it to your phone + speaks it.

### 3. Live wiring (Telegram + smart_home)

```
$ .venv/bin/python -m setup_integrations
    -> prompts for TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID / HASS_URL / HASS_TOKEN / NEWSAPI_KEY / ALPHAVANTAGE_KEY
    -> writes them into .env (backed up to .env.bak first)
    -> runs integration_health.all() and prints PASS / NOT CONFIGURED / FAIL per integration
```

For programmatic / UI access:

```bash
curl -sS http://127.0.0.1:5000/api/integrations/health
# (auth-gated by ULTRON_API_KEYS as usual)
```

## Modules

| File | Tests | Purpose |
|---|---:|---|
| `world_event_types.py` | 5 | `WorldEvent` dataclass (auto-clamped score) |
| `worldfeed_store.py` | 8 | JSON-backed ranked feed (mirrors `action_log.py`) |
| `world_event_sources.py` | 9 | RSSSource / NewsAPISource / AlphaVantageSource |
| `interest_matcher.py` | 7 | explicit interests.json overrides conversation_listener |
| `world_event_poller.py` | 6 | source registry + tick dispatch |
| `briefing_types.py` | 3 | `BriefingSchedule` dataclass |
| `briefing_scheduler.py` | 9 | croniter CRUD + `tick(now, window)` |
| `briefing_builder.py` | 6 | compose from worldfeed + queue + goals |
| `briefing_delivery.py` | 5 | fan-out to telegram + voice |
| `integration_health.py` | 8 | uniform health probes for the four integrations |
| `setup_integrations.py` | 4 | interactive .env writer + smoke checks |
| `voice_engine.py` (modified) | 4 | "brief me now" / "what's new in the world" hook |
| `app.py` (modified) | 3 | `/api/integrations/health` route |
| `tests/test_phase6_integration.py` | 3 | end-to-end poller → briefing → delivery |

Total: **~80 new tests**, zero regression on the 964-test Phase 4 baseline.

## How to enable

```bash
export ULTRON_PHASE6_ENABLED=1
.venv/bin/python -m setup_integrations  # one-time
```

After that:

```python
import scenarios_builtin
scenarios_builtin.register_builtins()

import world_event_sources as wes, world_event_poller as wep
wep.register("hn",         wes.RSSSource("https://hnrss.org/frontpage"))
wep.register("newsapi",    wes.NewsAPISource(api_key=os.environ["NEWSAPI_KEY"]))
wep.register("av_quotes",  wes.AlphaVantageSource(api_key=os.environ["ALPHAVANTAGE_KEY"],
                                                  tickers=["AAPL","NVDA","MSFT"]))
wep.start()

import briefing_scheduler as bs
bs.add("morning", "0 8 * * *", channels=["telegram", "voice"])
```

A background tick loop (e.g., in `autonomous_loop.py`) then calls
`bs.tick()` once per minute.

## Defensive design

- `feedparser` and `croniter` are soft dependencies. If `import` fails,
  the module logs and disables itself; the rest of Phase 6 still works.
- Each source adapter catches its own exceptions; one rate-limit error
  never aborts the poller.
- `setup_integrations.py` backs up `.env` to `.env.bak` before writing.
- The voice hook sits ABOVE Phase 4 so `"brief me now"` never accidentally
  falls into scenario matching. The Phase 4 hook is preserved.
- `/api/integrations/health` returns 404 when the flag is off, so the
  surface area is invisible by default.

## How to test

```bash
.venv/bin/python -m pytest \
    tests/test_world_event_types.py \
    tests/test_worldfeed_store.py \
    tests/test_world_event_sources.py \
    tests/test_interest_matcher.py \
    tests/test_world_event_poller.py \
    tests/test_briefing_types.py \
    tests/test_briefing_scheduler.py \
    tests/test_briefing_builder.py \
    tests/test_briefing_delivery.py \
    tests/test_integration_health.py \
    tests/test_setup_integrations.py \
    tests/test_phase6_voice_hook.py \
    tests/test_phase6_health_route.py \
    tests/test_phase6_integration.py -v
```

## What's next

- A settings UI on `/api/integrations/health` for non-CLI configuration.
- Proactive offers when a very-high-score worldfeed item arrives.
- Stock-price rule engine (`alert me if AAPL drops 3%`).
