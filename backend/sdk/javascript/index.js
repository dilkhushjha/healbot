const path = require('path');
const { HealbotClient } = require('./lib/client');
const { patchPage } = require('./lib/pagePatch');

function loadPlaywright() {
  try {
    return require('@playwright/test');
  } catch (error) {
    return require(path.resolve(process.cwd(), 'node_modules', '@playwright', 'test'));
  }
}

const playwright = loadPlaywright();

function createHealbotTest(baseTest = playwright.test) {
  return baseTest.extend({
    page: async ({ page }, use, testInfo) => {
      const healbot = new HealbotClient();
      let liveTimer = null;
      let heartbeatTimer = null;
      let liveBusy = false;

      try {
        await healbot.startSession(`${testInfo.project.name} / ${testInfo.title}`);
        patchPage(page, healbot, testInfo);

        if (healbot.sessionId) {
          heartbeatTimer = setInterval(() => {
            healbot.heartbeat().catch(() => {});
          }, 15000);
        }

        if (healbot.sessionId && healbot.config.live_stream !== false) {
          const intervalMs = Math.max(Number(healbot.config.live_frame_interval_ms || 900), 500);
          liveTimer = setInterval(() => {
            if (liveBusy) return;
            liveBusy = true;
            healbot.streamFrame(page)
              .catch(() => {})
              .finally(() => {
                liveBusy = false;
              });
          }, intervalMs);
        }
      } catch (error) {
        healbot.log(`Disabled for this test: ${error.message}`, 'warn');
      }

      try {
        await use(page);
      } finally {
        if (liveTimer) clearInterval(liveTimer);
        if (heartbeatTimer) clearInterval(heartbeatTimer);
        if (healbot.sessionId) {
          const passed = testInfo.status === testInfo.expectedStatus;
          await healbot.event({
            page,
            status: passed ? 'passed' : 'failed',
            description: `Finished: ${testInfo.title}`,
            message: passed ? 'Playwright test completed successfully.' : `Playwright test finished with status ${testInfo.status}.`,
            includeScreenshot: true,
          }).catch((error) => {
            healbot.log(`Could not send final test event: ${error.message}`, 'warn');
          });
          await healbot.endSession().catch((error) => {
            healbot.log(`Could not end session: ${error.message}`, 'warn');
          });
        }
      }
    },
  });
}

const test = createHealbotTest(playwright.test);

module.exports = {
  ...playwright,
  HealbotClient,
  createHealbotTest,
  expect: playwright.expect,
  patchPage,
  test,
};
