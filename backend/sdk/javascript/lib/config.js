const fs = require('fs');
const os = require('os');
const path = require('path');

const DEFAULT_API_URL = 'http://localhost:8000';

function readJson(filePath) {
  if (!filePath || !fs.existsSync(filePath)) return {};
  try {
    const value = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    return value && typeof value === 'object' ? value : {};
  } catch (error) {
    console.warn(`[Healbot] Could not read config ${filePath}: ${error.message}`);
    return {};
  }
}

function profilePath() {
  if (process.env.HEALBOT_PROFILE) {
    return path.resolve(process.env.HEALBOT_PROFILE);
  }
  if (process.env.APPDATA) {
    return path.join(process.env.APPDATA, 'Healbot', 'profile.json');
  }
  return path.join(os.homedir(), '.healbot', 'profile.json');
}

function projectConfigPath(cwd = process.cwd()) {
  if (process.env.HEALBOT_CONFIG) {
    return path.resolve(process.env.HEALBOT_CONFIG);
  }
  return path.resolve(cwd, 'healbot.config.json');
}

function loadConfig(options = {}) {
  const cwd = options.cwd || process.cwd();
  const profile = readJson(profilePath());
  const project = readJson(options.configPath || projectConfigPath(cwd));
  return {
    ...profile,
    ...project,
    api_url: (
      project.api_url ||
      process.env.HEALBOT_API_URL ||
      process.env.HEALBOT_URL ||
      profile.api_url ||
      DEFAULT_API_URL
    ).replace(/\/$/, ''),
    api_key: (
      project.api_key ||
      process.env.HEALBOT_API_KEY ||
      profile.api_key ||
      ''
    ).trim(),
    dashboard_url: (
      project.dashboard_url ||
      profile.dashboard_url ||
      'http://localhost:3000'
    ).replace(/\/$/, ''),
    framework: project.framework || 'playwright-js',
    project_id: project.project_id || '',
    environment_id: project.environment_id || '',
    live_stream: project.live_stream !== false,
    live_frame_interval_ms: Number(project.live_frame_interval_ms || 900),
  };
}

module.exports = {
  DEFAULT_API_URL,
  loadConfig,
  profilePath,
  projectConfigPath,
};
