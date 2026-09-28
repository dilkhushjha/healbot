# Healbot SDK Quickstart

Healbot can run without setting `HEALBOT_API_KEY` in every terminal.

## Option 1: Dashboard login

1. Start the backend and frontend.
2. Register or connect in the Healbot dashboard.
3. The dashboard saves a local SDK profile automatically.
4. Run your tests normally.

The SDK reads the profile before falling back to environment variables.

## Option 2: CLI configure

```bash
python -m healbot configure --api-key hb_live_xxx --api-url http://localhost:8000
python -m healbot doctor
```

## Python usage

```python
from healbot import HealBot

hb = HealBot()
hb.activate()

# run your existing Selenium, Playwright, or Robot tests

hb.deactivate()
```

Target a configured Healbot environment:

```python
from healbot_sdk import HealBotClient

client = HealBotClient()
batch = client.submit_batch(
    "Smoke suite",
    scripts=[journey],
    environment_id="staging_env_id",
)
```

Environment variables still work and take priority:

- `HEALBOT_API_KEY`
- `HEALBOT_API_URL`
- `HEALBOT_URL`
- `HEALBOT_PROFILE`

## JavaScript Playwright usage

Install the SDK into a Playwright project:

```bash
npm install --save-dev file:C:/Users/91916/Desktop/AI/SaaS/v8/Healbot/backend/sdk/javascript
```

Add `healbot.config.json` in the Playwright project root:

```json
{
  "api_url": "http://localhost:8000",
  "dashboard_url": "http://localhost:3000",
  "api_key": "hb_live_your_key",
  "project_name": "My QA Workspace",
  "project_id": "",
  "environment_id": "",
  "framework": "playwright-js",
  "live_stream": true,
  "live_frame_interval_ms": 900
}
```

Then replace the shared Playwright import:

```js
const base = require('@playwright/test');
```

with:

```js
const base = require('@healbot/playwright');
```

Existing `base.test.extend(...)`, `expect`, and page objects continue to work.
The SDK starts sessions, streams browser frames, patches `page.locator`, and
invokes Healbot when locator actions fail.
