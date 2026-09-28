const http = require('http');
const https = require('https');
const { URL } = require('url');
const { loadConfig } = require('./config');

class HealbotClient {
  constructor(options = {}) {
    this.config = loadConfig(options);
    this.apiUrl = this.config.api_url;
    this.apiKey = this.config.api_key;
    this.sessionId = '';
    this.runId = '';
    this.batchId = '';
    this.enabled = Boolean(this.apiKey);
    this.verbose = options.verbose !== false;

    if (!this.enabled) {
      this.log('Missing api_key. Add healbot.config.json or connect once in the Healbot dashboard.', 'warn');
    }
  }

  async startSession(name = 'Playwright run') {
    if (!this.enabled) return null;
    const result = await this.post('/sessions/start', {
      name,
      framework: this.config.framework || 'playwright-js',
      project_id: this.config.project_id || '',
      environment_id: this.config.environment_id || '',
    });
    this.sessionId = result.session_id || '';
    this.runId = result.run_id || '';
    this.batchId = result.batch_id || '';
    this.log(`Session started: ${this.sessionId}`);
    if (this.runId) {
      this.log(`Dashboard stream: ${this.config.dashboard_url}/stream/${this.runId}`);
    }
    return result;
  }

  async endSession() {
    if (!this.enabled || !this.sessionId) return null;
    const result = await this.post('/sessions/end', { session_id: this.sessionId });
    this.log(`Session ended: status=${result.status} healed=${result.healed || 0} failed=${result.failed || 0}`);
    this.sessionId = '';
    this.runId = '';
    this.batchId = '';
    return result;
  }

  async event({
    page,
    eventType = 'step',
    status = 'running',
    description = '',
    selector = '',
    healedSelector = '',
    strategy = '',
    llmUsed = false,
    message = '',
    includeScreenshot = false,
  } = {}) {
    if (!this.enabled || !this.sessionId) return null;
    const screenshot = includeScreenshot && page ? await this.captureScreenshot(page) : '';
    return this.post('/sessions/event', {
      session_id: this.sessionId,
      event_type: eventType,
      status,
      description,
      selector,
      healed_selector: healedSelector,
      strategy,
      llm_used: llmUsed,
      screenshot,
      message,
    });
  }

  async streamFrame(page, description = 'Live browser frame') {
    return this.event({
      page,
      eventType: 'browser_frame',
      status: 'running',
      description,
      includeScreenshot: true,
    });
  }

  async heartbeat(message = 'SDK heartbeat') {
    return this.event({
      eventType: 'heartbeat',
      status: 'running',
      message,
      includeScreenshot: false,
    });
  }

  async heal({ page, selector, intent = '', testName = '' }) {
    if (!this.enabled) return null;
    await this.event({
      page,
      status: 'healing',
      description: `Healing selector: ${selector}`,
      selector,
      includeScreenshot: true,
    }).catch(() => {});

    let html = '';
    try {
      html = await page.content();
    } catch {
      html = '';
    }

    let result = null;
    try {
      result = await this.post('/heal', {
        selector,
        html,
        intent,
        test_name: testName,
        session_id: this.sessionId || '',
      });
    } catch (error) {
      this.log(`Healing skipped: ${error.message}`, 'warn');
      return null;
    }

    if (result.llm_used) {
      this.log(`LLM used: ${result.llm_provider || 'provider'} / ${result.llm_model || 'model'}`);
    }

    if (result.success && result.healed) {
      this.log(`Healed selector: ${selector} -> ${result.healed}`);
      await this.event({
        page,
        status: 'healed',
        description: testName || `Healed selector: ${selector}`,
        selector,
        healedSelector: result.healed,
        strategy: result.strategy || '',
        llmUsed: Boolean(result.llm_used),
        includeScreenshot: true,
      }).catch(() => {});
      return result.healed;
    }

    await this.event({
      page,
      status: 'failed',
      description: testName || `Could not heal selector: ${selector}`,
      selector,
      message: 'Healbot could not find a replacement selector.',
      includeScreenshot: true,
    }).catch(() => {});
    return null;
  }

  async captureScreenshot(page) {
    try {
      const buffer = await page.screenshot({
        type: 'jpeg',
        quality: 65,
        fullPage: false,
      });
      return buffer.toString('base64');
    } catch {
      return '';
    }
  }

  async post(endpoint, body) {
    if (!this.apiKey) return {};
    return requestJson(`${this.apiUrl}${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.apiKey}`,
      },
      body,
      timeoutMs: 15000,
    });
  }

  log(message, level = 'info') {
    if (!this.verbose) return;
    const prefix = level === 'warn' ? 'WARN' : 'INFO';
    console.log(`[Healbot] ${prefix} ${message}`);
  }
}

function requestJson(url, options) {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    const payload = JSON.stringify(options.body || {});
    const transport = target.protocol === 'https:' ? https : http;
    const req = transport.request({
      method: options.method || 'POST',
      hostname: target.hostname,
      port: target.port,
      path: `${target.pathname}${target.search}`,
      headers: {
        ...options.headers,
        'Content-Length': Buffer.byteLength(payload),
      },
      timeout: options.timeoutMs || 15000,
    }, (res) => {
      let raw = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => { raw += chunk; });
      res.on('end', () => {
        const data = raw ? safeParse(raw) : {};
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(data.detail || data.message || `HTTP ${res.statusCode}`));
          return;
        }
        resolve(data);
      });
    });
    req.on('timeout', () => req.destroy(new Error('request timed out')));
    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

function safeParse(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

module.exports = {
  HealbotClient,
};
