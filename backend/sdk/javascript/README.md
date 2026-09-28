# @healbot/playwright

Plug-and-play Healbot SDK for JavaScript Playwright frameworks.

## Install locally while developing Healbot

```bash
npm install --save-dev file:C:/Users/91916/Desktop/AI/SaaS/v8/Healbot/backend/sdk/javascript
```

## Add one config file

Create `healbot.config.json` in the Playwright project root:

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

Only `api_key` is required when the dashboard has already saved a local profile.

## Use the drop-in Playwright export

In existing specs or a shared fixture, replace:

```js
const base = require('@playwright/test');
```

with:

```js
const base = require('@healbot/playwright');
```

Existing `base.test.extend(...)`, `expect`, and Playwright exports continue to work.
The SDK automatically starts a Healbot session, streams browser frames, patches
`page.locator`, and invokes healing when locator actions fail.

## Reporter-only mode

If a team wants run visibility before healing, add this reporter in
`playwright.config.js`:

```js
reporter: [
  ['list'],
  ['@healbot/playwright/reporter'],
]
```

Reporter-only mode records test results but cannot stream page screenshots or
self-heal locators because Playwright reporters do not receive the `page`.
