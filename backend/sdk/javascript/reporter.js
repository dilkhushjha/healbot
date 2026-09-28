const { HealbotClient } = require('./lib/client');

class HealbotReporter {
  constructor() {
    this.client = new HealbotClient();
  }

  async onBegin(config, suite) {
    const total = suite.allTests().length;
    await this.client.startSession(`Playwright suite - ${total} tests`).catch((error) => {
      this.client.log(`Reporter disabled: ${error.message}`, 'warn');
    });
  }

  async onTestEnd(test, result) {
    if (!this.client.sessionId) return;
    const passed = result.status === test.expectedStatus;
    await this.client.event({
      status: passed ? 'passed' : 'failed',
      description: test.titlePath().join(' / '),
      message: `Playwright result: ${result.status}`,
      includeScreenshot: false,
    }).catch(() => {});
  }

  async onEnd() {
    await this.client.endSession().catch((error) => {
      this.client.log(`Reporter could not end session: ${error.message}`, 'warn');
    });
  }
}

module.exports = HealbotReporter;
