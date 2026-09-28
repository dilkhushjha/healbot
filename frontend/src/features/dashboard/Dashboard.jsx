import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API, apiRequest, persistLocalProfile } from "./api";
import "./dashboard.css";

const tone = {
  running: ["#155eef", "#eff6ff", "#bfdbfe"],
  healing: ["#6941c6", "#f4f3ff", "#d9d6fe"],
  llm: ["#155eef", "#eff6ff", "#bfdbfe"],
  passed: ["#087443", "#ecfdf3", "#abefc6"],
  completed: ["#087443", "#ecfdf3", "#abefc6"],
  healed: ["#6941c6", "#f4f3ff", "#d9d6fe"],
  failed: ["#b42318", "#fff4ed", "#fed7aa"],
  error: ["#b42318", "#fff4ed", "#fed7aa"],
  ready: ["#087443", "#ecfdf3", "#abefc6"],
  idle: ["#475467", "#f8fafc", "#d0d5dd"],
  planned: ["#a15c07", "#fffbeb", "#fde68a"],
  active: ["#087443", "#ecfdf3", "#abefc6"],
  disabled: ["#475467", "#f8fafc", "#d0d5dd"],
  invited: ["#155eef", "#eff6ff", "#bfdbfe"],
  pending: ["#475467", "#f8fafc", "#d0d5dd"],
};

const navItems = [
  ["overview", "Overview"],
  ["live", "Live"],
  ["evidence", "Evidence"],
  ["setup", "Setup"],
  ["admin", "Admin"],
];

function statusColor(status) {
  return tone[String(status || "pending").toLowerCase()] || tone.pending;
}

function Badge({ status, label }) {
  const [color, bg, border] = statusColor(status);
  return (
    <span className="hb-pill" style={{ color, background: bg, borderColor: border }}>
      {label || status || "pending"}
    </span>
  );
}

function Icon({ children }) {
  return <span className="hb-icon" aria-hidden="true">{children}</span>;
}

function short(value, max = 64) {
  if (!value) return "-";
  const text = String(value);
  return text.length <= max ? text : `${text.slice(0, 30)}...${text.slice(-24)}`;
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 19);
  return date.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function pct(part, total) {
  return total ? Math.round((part / total) * 100) : 0;
}

function initials(value) {
  const parts = String(value || "QA").split(/[\s@._-]+/).filter(Boolean);
  return parts.slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "QA";
}

function targetLabel(batch) {
  const env = batch?.environment_snapshot || {};
  if (env.project_name && env.name) return `${env.project_name} / ${env.name}`;
  if (env.name) return env.name;
  if (env.project_name) return env.project_name;
  return batch?.environment_id || batch?.project_id || "Default workspace";
}

function isLiveStatus(status) {
  return ["queued", "running", "healing"].includes(String(status || "").toLowerCase());
}

function isTerminalStatus(status) {
  return ["passed", "failed", "healed", "error", "completed", "cancelled"].includes(String(status || "").toLowerCase());
}

function releaseScore(analytics, meta, runners) {
  const total = analytics?.total_scripts || 0;
  const failures = analytics?.total_failures || 0;
  const healRate = Number(analytics?.heal_rate_pct || 0);
  const passConfidence = total ? pct(Math.max(total - failures, 0), total) : 72;
  const readyRunners = runners.filter((item) => item.health?.ready).length;
  const runnerScore = runners.length ? pct(readyRunners, runners.length) : 40;
  const aiScore = meta?.llm?.ready ? 100 : 55;
  return Math.round((passConfidence * 0.5) + (Math.min(healRate, 100) * 0.2) + (runnerScore * 0.15) + (aiScore * 0.15));
}

function Section({ title, subtitle, action, children, className = "" }) {
  return (
    <section className={`hb-panel ${className}`}>
      <div className="hb-section-head">
        <div>
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Stat({ label, value, detail, toneName = "blue" }) {
  return (
    <div className={`hb-stat ${toneName}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function ProgressRing({ value }) {
  const clamped = Math.max(0, Math.min(100, value || 0));
  return (
    <div className="hb-score-ring" style={{ "--score": `${clamped}%` }}>
      <div>
        <strong>{clamped}</strong>
        <span>score</span>
      </div>
    </div>
  );
}

function TrendBars({ trend }) {
  const entries = Object.entries(trend || {}).slice(-10);
  if (!entries.length) return <div className="hb-empty compact">No trend data yet.</div>;
  const maxRuns = Math.max(...entries.map(([, item]) => item.runs || 0), 1);
  return (
    <div className="hb-bars">
      {entries.map(([day, item]) => (
        <div className="hb-bar" key={day} title={`${day}: ${item.runs || 0} runs`}>
          <span style={{ height: `${Math.max(10, ((item.runs || 0) / maxRuns) * 100)}%` }} />
          <small>{day.slice(5)}</small>
        </div>
      ))}
    </div>
  );
}

function AuthScreen({ mode, onSuccess, onSwitch }) {
  const isRegister = mode === "register";
  const [name, setName] = useState("QA Workspace");
  const [email, setEmail] = useState("qa@example.com");
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    setSaving(true);
    setError("");
    try {
      if (isRegister) {
        const result = await apiRequest("", "POST", "/auth/register", { name, email, tier: "free" });
        onSuccess({ key: result.api_key, tenantId: result.tenant_id, email, tier: result.tier });
      } else {
        const me = await apiRequest(key, "GET", "/auth/me");
        onSuccess({ key, tenantId: me.tenant?.id, email: me.tenant?.email, tier: me.tenant?.tier });
      }
    } catch (err) {
      setError(err.message || "Could not connect.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="hb-auth">
      <div className="hb-auth-card">
        <Brand />
        <h1>{isRegister ? "Create your QA command center" : "Connect your workspace"}</h1>
        <p>Run automation, watch execution, heal broken selectors, and keep evidence in one light workspace.</p>
        <div className="hb-form">
          {isRegister ? (
            <>
              <input className="hb-input" value={name} onChange={(event) => setName(event.target.value)} placeholder="Workspace name" />
              <input className="hb-input" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="Owner email" />
            </>
          ) : (
            <input className="hb-input" value={key} onChange={(event) => setKey(event.target.value)} placeholder="hb_live_..." />
          )}
          {error ? <div className="hb-error">{error}</div> : null}
          <button className="hb-btn primary" disabled={saving || (isRegister ? !name || !email : !key)} onClick={submit}>
            {saving ? "Working" : isRegister ? "Create workspace" : "Connect"}
          </button>
          <button className="hb-btn ghost" onClick={onSwitch}>
            {isRegister ? "I already have a key" : "Create a new workspace"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Brand() {
  return (
    <div className="hb-brand">
      <div className="hb-logo">
        <span className="hb-logo-mark">H</span>
      </div>
      <div>
        <strong>Healbot</strong>
        <span>Self-healing QA automation</span>
      </div>
    </div>
  );
}

function Shell({ auth, me, view, setView, onLogout, refresh, refreshing, children }) {
  return (
    <div className="hb-product">
      <aside className="hb-sidebar">
        <Brand />
        <nav className="hb-nav" aria-label="Healbot sections">
          {navItems.map(([id, label]) => (
            <button key={id} className={view === id ? "active" : ""} onClick={() => setView(id)}>
              <Icon>{label[0]}</Icon>
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="hb-side-status">
          <span>Workspace</span>
          <strong>{me?.tenant?.name || "QA workspace"}</strong>
          <small>{String(me?.role || auth.tier || "connected").replace("_", " ")}</small>
        </div>
      </aside>
      <main className="hb-main">
        <header className="hb-topbar">
          <div>
            <div className="hb-kicker">QA control plane</div>
            <h1>{navItems.find(([id]) => id === view)?.[1] || "Overview"}</h1>
          </div>
          <div className="hb-actions">
            <button className="hb-btn ghost" disabled={refreshing} onClick={refresh}>{refreshing ? "Refreshing" : "Refresh"}</button>
            <div className="hb-user">
              <div className="hb-avatar">{initials(me?.tenant?.name || auth.email)}</div>
              <div>
                <strong>{me?.tenant?.name || "QA workspace"}</strong>
                <span>{me?.tenant?.tier || auth.tier || "local"}</span>
              </div>
            </div>
            <button className="hb-btn ghost" onClick={onLogout}>Sign out</button>
          </div>
        </header>
        <div className="hb-content">{children}</div>
      </main>
    </div>
  );
}

function Overview({ analytics, batches, meta, projects, runners, auth, activeRun, latestScreenshot, latestFrameAt, streamState, runStatus, metrics, onOpenBatch, setView }) {
  const score = releaseScore(analytics, meta, runners);
  const running = batches.filter((batch) => isLiveStatus(batch.status));
  const latest = running[0] || batches[0];
  const total = analytics?.total_scripts || 0;
  const failures = analytics?.total_failures || 0;
  const passConfidence = total ? pct(Math.max(total - failures, 0), total) : 0;
  const readyRunners = runners.filter((item) => item.health?.ready).length;
  const healRate = analytics?.heal_rate_pct || 0;
  const runState = running.length ? "running" : latest ? latest.status : "idle";
  const headline = running.length ? "Execution in progress" : latest ? "Latest automation evidence" : "Connect a framework to start";
  const summary = running.length
    ? `${running.length} suite${running.length === 1 ? "" : "s"} streaming into Healbot now.`
    : latest
      ? `${latest.name || "Automation run"} finished with status ${latest.status}.`
      : "Install the SDK, add the config JSON, and your runs will appear here automatically.";
  const checks = [
    ["SDK", Boolean(auth.profilePath), auth.profilePath ? "Profile saved" : "Needs local profile"],
    ["AI", Boolean(meta?.llm?.ready), meta?.llm?.ready ? `${meta.llm.provider} / ${meta.llm.model}` : "Rules only"],
    ["Runners", readyRunners > 0, `${readyRunners}/${runners.length || 0} ready`],
    ["Queue", (meta?.queue_depth || 0) < 5, `${meta?.queue_depth || 0} waiting`],
  ];

  return (
    <>
      <section className="hb-ops-board">
        <div className="hb-ops-main">
          <div className="hb-ops-copy">
            <Badge status={runState} label={running.length ? "Live now" : latest ? latest.status : "not connected"} />
            <h2>{headline}</h2>
            <p>{summary}</p>
            <div className="hb-command-actions">
              {latest ? <button className="hb-btn primary" onClick={() => onOpenBatch(latest)}>{running.length ? "Watch live" : "Open run"}</button> : null}
              <button className="hb-btn ghost" onClick={() => setView("setup")}>Setup SDK</button>
            </div>
          </div>
          <LivePreview activeRun={activeRun} latestScreenshot={latestScreenshot} latestFrameAt={latestFrameAt} streamState={streamState} runStatus={runStatus} metrics={metrics} latest={latest} onOpenBatch={onOpenBatch} />
        </div>

        <aside className="hb-ops-side">
          <div className="hb-score-card calm">
            <ProgressRing value={score} />
            <div>
              <span>Release confidence</span>
              <strong>{score >= 80 ? "Healthy" : score >= 60 ? "Watch closely" : "Needs setup"}</strong>
              <p>{passConfidence}% pass confidence across {total || 0} scripts.</p>
            </div>
          </div>
          {checks.map(([label, ok, detail]) => (
            <div className="hb-health-row" key={label}>
              <span className={ok ? "ok" : "warn"}>{ok ? "OK" : "!"}</span>
              <div>
                <strong>{label}</strong>
                <small>{detail}</small>
              </div>
            </div>
          ))}
        </aside>
      </section>

      <div className="hb-stat-grid">
        <Stat label="Pass confidence" value={`${passConfidence}%`} detail={`${total} scripts analyzed`} toneName="green" />
        <Stat label="Recovered selectors" value={analytics?.total_heals || 0} detail={`${healRate}% heal rate`} toneName="purple" />
        <Stat label="Live runs" value={running.length} detail={running.length ? "Streaming now" : "No active execution"} toneName="blue" />
        <Stat label="LLM calls today" value={analytics?.llm_calls_today || meta?.usage?.llm_calls_today || 0} detail={meta?.llm?.ready ? "AI healing ready" : "Not configured"} toneName="amber" />
      </div>

      <div className="hb-workbench">
        <Section title="Recent automation" subtitle="Latest suites with their final state.">
          <RunList batches={batches.slice(0, 7)} onOpenBatch={onOpenBatch} />
        </Section>
        <Section title="Run volume" subtitle="Recent execution trend.">
          <TrendBars trend={analytics?.daily_trend} />
        </Section>
      </div>
    </>
  );
}

function LivePreview({ activeRun, latestScreenshot, latestFrameAt, streamState, runStatus, metrics, latest, onOpenBatch }) {
  return (
    <section className="hb-live-preview">
      <div className="hb-preview-head">
        <div>
          <h2>Live browser</h2>
          <p>{activeRun?.name || latest?.name || "No active run selected"}</p>
        </div>
        <Badge status={runStatus || latest?.status || "idle"} />
      </div>
      <BrowserFrame latestScreenshot={latestScreenshot} latestFrameAt={latestFrameAt} streamState={streamState} runStatus={runStatus || latest?.status} compact />
      <div className="hb-live-foot">
        <span>{metrics.healedSelectors || 0} heals</span>
        <span>{metrics.llmCalls || 0} LLM calls</span>
        <span>{metrics.failures || 0} failures</span>
        {latest ? <button className="hb-btn ghost" onClick={() => onOpenBatch(latest)}>Inspect</button> : null}
      </div>
    </section>
  );
}

function BrowserFrame({ latestScreenshot, latestFrameAt, streamState = "idle", runStatus, compact = false }) {
  const displayState = isLiveStatus(runStatus) ? streamState : (runStatus ? "ended" : streamState);
  const chipLabel = displayState === "connected" ? "Live" : displayState === "connecting" ? "Connecting" : displayState === "ended" ? "Ended" : displayState === "error" ? "Disconnected" : "Idle";
  return (
    <div className={`hb-browser ${compact ? "compact" : ""}`}>
      <div className="hb-browser-chrome">
        <span />
        <span />
        <span />
        <strong>runner viewport</strong>
        <em className={`hb-stream-chip ${displayState}`}>{chipLabel}</em>
      </div>
      {latestScreenshot ? (
        <div className="hb-frame-wrap">
          <img src={`data:image/png;base64,${latestScreenshot}`} alt="Live automation screenshot" />
          <div className="hb-frame-caption">
            <strong>{isLiveStatus(runStatus) ? "Execution running" : "Latest captured frame"}</strong>
            <span>{latestFrameAt ? `Frame at ${latestFrameAt}` : "Waiting for next frame"}</span>
          </div>
        </div>
      ) : (
        <div className="hb-empty-stage">
          <strong>Waiting for live frame</strong>
          <span>{streamState === "connecting" ? "Connecting to the run stream." : "Browser screenshots appear here as your SDK streams events."}</span>
        </div>
      )}
    </div>
  );
}

function RunList({ batches, onOpenBatch }) {
  if (!batches.length) return <div className="hb-empty">No runs yet. Trigger your framework and Healbot will attach automatically.</div>;
  return (
    <div className="hb-run-list">
      {batches.map((batch) => (
        <button className="hb-run-item" key={batch.id} onClick={() => onOpenBatch(batch)}>
          <div>
            <strong>{batch.name || "Automation run"}</strong>
            <span>{targetLabel(batch)} / {formatDate(batch.created_at)}</span>
          </div>
          <Badge status={batch.status} />
        </button>
      ))}
    </div>
  );
}

function LiveBanner({ batch, activeRun, runStatus, streamState, latestFrameAt, onOpenBatch }) {
  if (!batch && !activeRun) return null;
  const status = runStatus || batch?.status || "running";
  if (!isLiveStatus(status)) return null;
  return (
    <section className="hb-live-banner">
      <div className="hb-live-pulse" />
      <div>
        <strong>Execution is running live</strong>
        <span>{activeRun?.name || batch?.name || "Automation run"}{latestFrameAt ? ` / last frame ${latestFrameAt}` : ""}</span>
      </div>
      <Badge status={streamState === "connected" ? "running" : status} label={streamState === "connected" ? "stream connected" : status} />
      {batch ? <button className="hb-btn primary" onClick={() => onOpenBatch(batch)}>Watch live</button> : null}
    </section>
  );
}

function LiveRun({ activeRun, steps, logs, activityEvents, latestScreenshot, latestFrameAt, streamState, runStatus, metrics, batches, onOpenBatch }) {
  const done = steps.filter((step) => ["pass", "passed", "healed", "fail", "failed"].includes(step.status)).length;
  return (
    <>
      <div className="hb-live-layout">
        <section className="hb-theatre">
          <div className="hb-theatre-head">
            <div>
              <Badge status={runStatus || "idle"} />
              <h2>{activeRun?.name || "Live execution theatre"}</h2>
              <p>{activeRun?.run_id || "Open a run to inspect the browser, timeline, and evidence."}</p>
            </div>
            <div className="hb-mini-stats">
              <Stat label="Steps" value={`${done}/${steps.length || 0}`} toneName="blue" />
              <Stat label="Heals" value={metrics.healedSelectors || 0} toneName="purple" />
              <Stat label="Failures" value={metrics.failures || 0} toneName="red" />
            </div>
          </div>
          <BrowserFrame latestScreenshot={latestScreenshot} latestFrameAt={latestFrameAt} streamState={streamState} runStatus={runStatus} />
        </section>
        <div className="hb-live-side">
          <ActivityPanel events={activityEvents} metrics={metrics} />
          <section className="hb-timeline-panel">
            <div className="hb-section-head">
              <div>
                <h2>Timeline</h2>
                <p>Selector decisions, pass/fail steps, and healing strategy.</p>
              </div>
            </div>
            <div className="hb-timeline">
              {steps.length ? steps.map((step) => <Step key={step.id} step={step} />) : <div className="hb-empty compact">Waiting for step events.</div>}
            </div>
          </section>
        </div>
      </div>
      <div className="hb-grid-two">
        <Section title="Available runs" subtitle="Switch context without leaving the live theatre.">
          <RunList batches={batches.slice(0, 8)} onOpenBatch={onOpenBatch} />
        </Section>
        <Section title="Runner logs" subtitle={`${logs.length} recent events`}>
          <div className="hb-log-list">
            {logs.length ? logs.slice(-80).map((entry, index) => (
              <div className="hb-code" key={`${entry.time}-${index}`}>{entry.time || ""} {entry.stage || "RUN"} - {entry.message || JSON.stringify(entry)}</div>
            )) : <div className="hb-empty compact">Logs will stream during a run.</div>}
          </div>
        </Section>
      </div>
    </>
  );
}

function Step({ step }) {
  return (
    <div className="hb-step">
      <div className="hb-step-head">
        <strong>{step.description || step.id}</strong>
        <Badge status={step.status} />
      </div>
      {step.selector || step.original_selector ? <div className="hb-code">{short(step.selector || step.original_selector, 92)}</div> : null}
      {step.healed_selector ? <div className="hb-code healed">healed: {short(step.healed_selector, 92)}</div> : null}
      {step.strategy ? <small>Strategy: {step.strategy}{step.llm_used ? " with LLM review" : ""}</small> : null}
    </div>
  );
}

function ActivityPanel({ events, metrics }) {
  const latest = events.slice(-6).reverse();
  const active = latest.find((event) => ["healing_started", "llm_invoked"].includes(event.phase));
  return (
    <section className={`hb-activity-panel ${active ? "active" : ""}`}>
      <div className="hb-section-head">
        <div>
          <h2>Healing activity</h2>
          <p>Live AI and self-healing decisions from the current run.</p>
        </div>
        <Badge status={active?.phase === "llm_invoked" ? "llm" : active ? "healing" : "idle"} label={active?.phase === "llm_invoked" ? "LLM invoked" : active ? "Healing" : "Watching"} />
      </div>
      <div className="hb-ai-summary">
        <Stat label="LLM calls" value={metrics.llmCalls || 0} toneName="blue" />
        <Stat label="Heals" value={metrics.healedSelectors || 0} toneName="purple" />
      </div>
      <div className="hb-activity-list">
        {latest.length ? latest.map((event, index) => (
          <div className={`hb-activity-item ${event.type === "llm_activity" ? "llm" : "healing"}`} key={`${event.time || ""}-${event.phase}-${index}`}>
            <span>{event.type === "llm_activity" ? "AI" : "Heal"}</span>
            <div>
              <strong>{event.message || event.phase}</strong>
              <small>
                {event.provider ? `${event.provider}/${event.model || "model"}` : short(event.selector, 70)}
                {event.intent ? ` / ${event.intent}` : ""}
              </small>
            </div>
          </div>
        )) : <div className="hb-empty compact">No healing activity yet. When a selector breaks, updates appear here immediately.</div>}
      </div>
    </section>
  );
}

function Evidence({ analytics, selectors, usage, meta }) {
  return (
    <>
      <section className="hb-evidence-hero">
        <div>
          <Badge status={meta?.llm?.ready ? "ready" : "planned"} label={meta?.llm?.ready ? "AI connected" : "Rules active"} />
          <h2>Proof your automation recovered correctly.</h2>
          <p>Evidence is organized around broken selectors, repair strategies, and AI usage so QA leads can trust the repair path.</p>
        </div>
        <div className="hb-stat-grid tight">
          <Stat label="Total heals" value={analytics?.total_heals || 0} toneName="purple" />
          <Stat label="Heal rate" value={`${analytics?.heal_rate_pct || 0}%`} toneName="green" />
          <Stat label="LLM calls today" value={usage?.llm_calls_today || 0} toneName="blue" />
        </div>
      </section>
      <Section title="Selector intelligence" subtitle="Most broken selectors and how Healbot resolved them.">
        {selectors.length ? (
          <div className="hb-table-wrap">
            <table className="hb-table">
              <thead><tr><th>Broken selector</th><th>Breaks</th><th>Recovered</th><th>Primary strategy</th></tr></thead>
              <tbody>{selectors.map((row) => (
                <tr key={row.selector}>
                  <td className="hb-code">{row.selector}</td>
                  <td>{row.break_count}</td>
                  <td>{row.healed_count} ({row.heal_rate}%)</td>
                  <td>{row.top_strategy || "-"}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <div className="hb-empty">No healing evidence yet. Once a selector breaks, Healbot records the repair path here.</div>}
      </Section>
    </>
  );
}

function Setup({ projects, runners, onCreateProject, onCreateEnvironment, onCreateRunner }) {
  const [projectName, setProjectName] = useState("My QA Workspace");
  const [envName, setEnvName] = useState("Local web");
  const [baseUrl, setBaseUrl] = useState("");
  const [runnerName, setRunnerName] = useState("Local Playwright");
  const [creatingDefault, setCreatingDefault] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const activeProject = projects[0];
  const activeEnvironment = activeProject?.environments?.[0];
  const hasWorkspace = Boolean(activeProject);
  const configJson = {
    api_url: API,
    api_key: "hb_live_your_key",
    project_name: activeProject?.name || "My QA Workspace",
    project_id: activeProject?.id || "",
    environment_id: activeEnvironment?.id || "",
  };

  async function createDefaultWorkspace() {
    setCreatingDefault(true);
    try {
      const created = await onCreateProject({ name: projectName.trim() || "My QA Workspace" });
      if (created?.id) {
        await onCreateEnvironment(created.id, {
          name: envName.trim() || "Local web",
          base_url: baseUrl,
          framework: "playwright",
          browser: "chromium",
          platform: "web",
        });
      }
    } finally {
      setCreatingDefault(false);
    }
  }

  return (
    <div className="hb-setup-grid">
      <Section title="Framework setup" subtitle="Start with one default workspace. Advanced routing can wait.">
        <div className="hb-setup-hero">
          <Badge status={hasWorkspace ? "ready" : "pending"} label={hasWorkspace ? "ready" : "setup needed"} />
          <h3>{hasWorkspace ? "Your default workspace is ready" : "Use Healbot with the default workspace"}</h3>
          <p>
            A project is just a folder for your test runs. A target profile is optional metadata for browser, platform, and base URL.
            You can run Healbot without managing those details manually.
          </p>
          {!hasWorkspace ? (
            <div className="hb-form-row setup-default">
              <input className="hb-input" value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="Workspace name" />
              <button className="hb-btn primary" disabled={creatingDefault || !projectName.trim()} onClick={createDefaultWorkspace}>
                {creatingDefault ? "Creating" : "Use default setup"}
              </button>
            </div>
          ) : (
            <div className="hb-ready-box">
              <strong>{activeProject.name}</strong>
              <span>{activeEnvironment ? `${activeEnvironment.name} / ${activeEnvironment.framework} / ${activeEnvironment.browser}` : "Runs will use Healbot defaults."}</span>
            </div>
          )}
        </div>

        <div className="hb-code-block hb-config-card">
          <strong>Minimal framework config</strong>
          <p>Paste this in your framework and replace only the API key.</p>
          <pre>{JSON.stringify(configJson, null, 2)}</pre>
        </div>
      </Section>
      <Section title="What these fields mean" subtitle="Plain language, no platform jargon.">
        <div className="hb-definition-list">
          <div>
            <strong>Workspace</strong>
            <span>Groups runs for one product, app, or QA framework.</span>
          </div>
          <div>
            <strong>Target profile</strong>
            <span>Optional. Stores base URL, browser, platform, and future cloud runner settings.</span>
          </div>
          <div>
            <strong>Runner</strong>
            <span>Optional. Describes where tests execute today locally and later in cloud.</span>
          </div>
          <div>
            <strong>API key</strong>
            <span>The only required value your framework needs to send runs to Healbot.</span>
          </div>
        </div>
      </Section>
      <Section
        title="Advanced routing"
        subtitle="Use this only when you want separate staging, production, mobile, or browser targets."
        className="wide"
        action={<button className="hb-btn ghost" onClick={() => setShowAdvanced((value) => !value)}>{showAdvanced ? "Hide" : "Show"} advanced</button>}
      >
        {showAdvanced ? (
          <div className="hb-advanced-setup">
            <div className="hb-form-row three">
              <input className="hb-input" value={envName} onChange={(e) => setEnvName(e.target.value)} placeholder={activeProject ? `Target for ${activeProject.name}` : "Create default workspace first"} />
              <input className="hb-input" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="Base URL, optional" />
              <button className="hb-btn ghost" disabled={!activeProject || !envName.trim()} onClick={async () => { await onCreateEnvironment(activeProject.id, { name: envName, base_url: baseUrl, framework: "playwright", browser: "chromium", platform: "web" }); setEnvName("Local web"); setBaseUrl(""); }}>Add target</button>
            </div>
            <div className="hb-form-row">
              <input className="hb-input" value={runnerName} onChange={(e) => setRunnerName(e.target.value)} placeholder="Runner profile name" />
              <button className="hb-btn primary" disabled={!runnerName.trim()} onClick={async () => { await onCreateRunner({ name: runnerName, provider: "local", framework: "playwright", browser: "chromium", platform: "web", concurrency: 1, status: "available" }); setRunnerName("Local Playwright"); }}>Add runner</button>
            </div>
            <RunProjects projects={projects} />
            <div className="hb-runner-grid">
              {runners.map((runner) => (
                <div className="hb-runner" key={runner.id}>
                  <Badge status={runner.health?.ready ? "ready" : "planned"} label={runner.health?.ready ? "ready" : "planned"} />
                  <strong>{runner.name}</strong>
                  <span>{runner.provider} / {runner.framework} / {runner.browser}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="hb-empty compact">Advanced routing is hidden because most teams do not need it on day one.</div>
        )}
      </Section>
    </div>
  );
}

function RunProjects({ projects }) {
  if (!projects.length) return <div className="hb-empty compact">Create a project to generate SDK IDs.</div>;
  return (
    <div className="hb-project-grid">
      {projects.map((project) => (
        <div className="hb-project" key={project.id}>
          <strong>{project.name}</strong>
          <code>project_id: {project.id}</code>
          {(project.environments || []).map((env) => <code key={env.id}>environment_id: {env.id} - {env.name}</code>)}
        </div>
      ))}
    </div>
  );
}

function Admin({ auth, me, meta, apiKeys, teamUsers, onCreateKey, onInvite }) {
  const [keyName, setKeyName] = useState("automation runner");
  const [createdKey, setCreatedKey] = useState("");
  const [email, setEmail] = useState("");

  return (
    <div className="hb-grid-two">
      <Section title="Workspace" subtitle="Tenant, SDK profile, and runtime identity.">
        <table className="hb-table compact">
          <tbody>
            <tr><td>Organisation</td><td>{me?.tenant?.name || "-"}</td></tr>
            <tr><td>Role</td><td>{String(me?.role || "-").replace("_", " ")}</td></tr>
            <tr><td>API URL</td><td className="hb-code">{API}</td></tr>
            <tr><td>SDK profile</td><td className="hb-code">{auth.profilePath || "Not saved yet"}</td></tr>
            <tr><td>LLM</td><td>{meta?.llm?.ready ? `${meta.llm.provider} / ${meta.llm.model}` : (meta?.llm?.message || "LLM not configured")}</td></tr>
          </tbody>
        </table>
      </Section>
      <Section title="API keys" subtitle="Full keys are visible to workspace admins and used by SDKs or CI runners.">
        <div className="hb-form-row">
          <input className="hb-input" value={keyName} onChange={(e) => setKeyName(e.target.value)} />
          <button className="hb-btn primary" onClick={async () => { const result = await onCreateKey({ name: keyName }); setCreatedKey(result.api_key || ""); }}>Create key</button>
        </div>
        {createdKey ? <div className="hb-code-block"><code>{createdKey}</code></div> : null}
        {apiKeys.length ? <table className="hb-table compact"><tbody>{apiKeys.map((key) => <tr key={key.key}><td className="hb-code">{key.key}</td><td>{key.name}</td><td><Badge status={key.is_active ? "active" : "disabled"} /></td></tr>)}</tbody></table> : <div className="hb-empty compact">No keys loaded.</div>}
      </Section>
      <Section title="Team" subtitle="Invite QA leads, engineers, and read-only viewers." className="wide">
        <div className="hb-form-row">
          <input className="hb-input" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="teammate@company.com" />
          <button className="hb-btn primary" disabled={!email.trim()} onClick={async () => { await onInvite({ email, name: email.split("@")[0], role: "qa_engineer" }); setEmail(""); }}>Invite</button>
        </div>
        {teamUsers.length ? <table className="hb-table compact"><tbody>{teamUsers.map((user) => <tr key={user.id}><td>{user.name}<div className="hb-code">{user.email}</div></td><td>{user.role}</td><td><Badge status={user.status} /></td></tr>)}</tbody></table> : <div className="hb-empty compact">No team members loaded.</div>}
      </Section>
    </div>
  );
}

export default function Dashboard() {
  const [auth, setAuth] = useState(() => {
    try { return JSON.parse(localStorage.getItem("hb_auth") || "null"); } catch { return null; }
  });
  const [authMode, setAuthMode] = useState("register");
  const [view, setView] = useState("overview");
  const [data, setData] = useState({ batches: [], analytics: {}, selectors: [], usage: {}, meta: {}, me: null, projects: [], runners: [], keys: [], users: [] });
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [activeRun, setActiveRun] = useState(null);
  const [steps, setSteps] = useState([]);
  const [logs, setLogs] = useState([]);
  const [activityEvents, setActivityEvents] = useState([]);
  const [metrics, setMetrics] = useState({ llmCalls: 0, visionCalls: 0, healedSelectors: 0, failures: 0 });
  const [runStatus, setRunStatus] = useState("");
  const [latestScreenshot, setLatestScreenshot] = useState("");
  const [latestFrameAt, setLatestFrameAt] = useState("");
  const [streamState, setStreamState] = useState("idle");
  const esRef = useRef(null);
  const autoAttachRef = useRef("");

  const call = useCallback((method, path, body) => apiRequest(auth?.key, method, path, body), [auth?.key]);

  const refresh = useCallback(async () => {
    if (!auth?.key) return;
    setRefreshing(true);
    setError("");
    try {
      const [batches, analytics, selectors, usage, me, projects, runners, meta] = await Promise.all([
        call("GET", "/batches"),
        call("GET", "/analytics/overview"),
        call("GET", "/analytics/selectors"),
        call("GET", "/analytics/usage"),
        call("GET", "/auth/me"),
        call("GET", "/projects"),
        call("GET", "/runners/capabilities"),
        fetch(`${API}/meta`).then((response) => response.json()).catch(() => ({})),
      ]);
      let keys = [];
      let users = [];
      if (me?.permissions?.can_manage_api_keys) keys = await call("GET", "/auth/keys").catch(() => []);
      if (me?.permissions?.can_manage_users) users = await call("GET", "/auth/users").catch(() => []);
      setData({ batches, analytics, selectors, usage, me, projects, runners, meta, keys, users });
    } catch (err) {
      setError(err.message || "Unable to load dashboard.");
    } finally {
      setRefreshing(false);
    }
  }, [auth?.key, call]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => () => { if (esRef.current) esRef.current.close(); }, []);

  async function handleLogin(info) {
    const profile = await persistLocalProfile(info.key).catch(() => null);
    const next = profile?.profile_path ? { ...info, profilePath: profile.profile_path } : info;
    setAuth(next);
    localStorage.setItem("hb_auth", JSON.stringify(next));
  }

  function logout() {
    if (esRef.current) esRef.current.close();
    localStorage.removeItem("hb_auth");
    setAuth(null);
  }

  const openBatch = useCallback(async (batch, options = {}) => {
    const navigate = options.navigate !== false;
    const runs = await call("GET", `/batches/${batch.id}/runs`);
    const run = runs?.[0];
    if (!run?.id) {
      if (navigate) setView("live");
      return;
    }
    if (esRef.current) esRef.current.close();
    setActiveRun({ run_id: run.id, batch_id: batch.id, name: batch.name });
    setSteps([]);
    setLogs([]);
    setActivityEvents([]);
    setMetrics({ llmCalls: 0, visionCalls: 0, healedSelectors: 0, failures: 0 });
    setLatestScreenshot(run.latest_screenshot || "");
    setLatestFrameAt(run.latest_frame_at || "");
    setRunStatus(run.status || "running");
    setStreamState("connecting");
    localStorage.setItem("hb_active_batch", JSON.stringify({ batch_id: batch.id, run_id: run.id }));
    if (navigate) setView("live");

    const source = new EventSource(`${API}/stream/${run.id}?api_key=${encodeURIComponent(auth.key)}`);
    esRef.current = source;
    source.onopen = () => setStreamState("connected");
    source.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "done") {
        setRunStatus(message.payload?.status || message.status || "completed");
        setStreamState("ended");
        source.close();
        return;
      }
      if (message.type === "snapshot") {
        const status = message.payload?.status || "running";
        setRunStatus(status);
        if (message.payload?.metrics) setMetrics(message.payload.metrics);
        if (message.payload?.latest_screenshot) setLatestScreenshot(message.payload.latest_screenshot);
        if (message.payload?.latest_frame_at) setLatestFrameAt(message.payload.latest_frame_at);
        if (isTerminalStatus(status)) {
          setStreamState("ended");
          source.close();
          refresh();
        }
        return;
      }
      if (message.type !== "log") return;
      const entry = message.payload || {};
      if (entry.screenshot) {
        setLatestScreenshot(entry.screenshot);
        setLatestFrameAt(entry.time || new Date().toLocaleTimeString());
      }
      if (entry.type === "browser_frame") return;
      if (entry.type === "healing_activity" || entry.type === "llm_activity") {
        setActivityEvents((prev) => [...prev.slice(-30), entry]);
        return;
      }
      if (entry.type === "step") {
        if (entry.status === "healing") {
          setActivityEvents((prev) => [...prev.slice(-30), {
            type: "healing_activity",
            phase: "healing_started",
            status: "healing",
            selector: entry.original_selector,
            message: "Healing started for a broken selector",
            time: entry.time,
          }]);
        }
        setSteps((prev) => {
          const id = entry.step_id || entry.id || `${Date.now()}`;
          const next = {
            id,
            description: entry.description,
            selector: entry.original_selector,
            original_selector: entry.original_selector,
            healed_selector: entry.healed_selector || entry.healed,
            status: entry.status || "pending",
            strategy: entry.strategy,
            llm_used: entry.llm_used,
          };
          const existing = prev.findIndex((item) => item.id === id);
          if (existing === -1) return [...prev, next];
          return prev.map((item) => item.id === id ? { ...item, ...next } : item);
        });
      } else {
        setLogs((prev) => [...prev.slice(-250), entry]);
      }
    };
    source.onerror = () => {
      setRunStatus("error");
      setStreamState("error");
      source.close();
    };
  }, [auth?.key, call, refresh]);

  useEffect(() => {
    if (!activeRun?.batch_id || !data.batches.length) return;
    const current = data.batches.find((batch) => batch.id === activeRun.batch_id);
    if (!current || !isTerminalStatus(current.status)) return;
    setRunStatus((status) => isLiveStatus(status) ? current.status : status || current.status);
    setStreamState((state) => state === "connected" || state === "connecting" ? "ended" : state);
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, [activeRun?.batch_id, data.batches]);

  useEffect(() => {
    if (!auth?.key || !data.batches.length) return;
    const runningBatch = data.batches.find((batch) => isLiveStatus(batch.status));
    let target = runningBatch;
    let navigate = Boolean(runningBatch);

    if (!target) {
      try {
        const saved = JSON.parse(localStorage.getItem("hb_active_batch") || "null");
        target = data.batches.find((batch) => batch.id === saved?.batch_id);
      } catch {
        target = null;
      }
      navigate = false;
    }

    if (!target) return;
    if (activeRun?.batch_id === target.id && esRef.current) return;
    const attachKey = `${target.id}:${target.status}`;
    if (autoAttachRef.current === attachKey) return;
    autoAttachRef.current = attachKey;
    openBatch(target, { navigate });
  }, [auth?.key, data.batches, activeRun?.batch_id, openBatch]);

  const actions = useMemo(() => ({
    createProject: async (payload) => { const result = await call("POST", "/projects", payload); await refresh(); return result; },
    createEnvironment: async (projectId, payload) => { const result = await call("POST", `/projects/${projectId}/environments`, payload); await refresh(); return result; },
    createRunner: async (payload) => { const result = await call("POST", "/runners/capabilities", payload); await refresh(); return result; },
    createKey: async (payload) => { const result = await call("POST", "/auth/keys", payload); await refresh(); return result; },
    invite: async (payload) => { await call("POST", "/auth/users", payload); await refresh(); },
  }), [call, refresh]);

  if (!auth) {
    return <AuthScreen mode={authMode} onSuccess={handleLogin} onSwitch={() => setAuthMode(authMode === "register" ? "connect" : "register")} />;
  }

  return (
    <Shell auth={auth} me={data.me} view={view} setView={setView} onLogout={logout} refresh={refresh} refreshing={refreshing}>
      {error ? <div className="hb-error">{error}</div> : null}
      <LiveBanner batch={data.batches.find((batch) => isLiveStatus(batch.status))} activeRun={activeRun} runStatus={runStatus} streamState={streamState} latestFrameAt={latestFrameAt} onOpenBatch={openBatch} />
      {view === "overview" ? <Overview analytics={data.analytics} batches={data.batches} meta={data.meta} projects={data.projects} runners={data.runners} auth={auth} activeRun={activeRun} latestScreenshot={latestScreenshot} latestFrameAt={latestFrameAt} streamState={streamState} runStatus={runStatus} metrics={metrics} onOpenBatch={openBatch} setView={setView} /> : null}
      {view === "live" ? <LiveRun activeRun={activeRun} steps={steps} logs={logs} activityEvents={activityEvents} latestScreenshot={latestScreenshot} latestFrameAt={latestFrameAt} streamState={streamState} runStatus={runStatus} metrics={metrics} batches={data.batches} onOpenBatch={openBatch} /> : null}
      {view === "evidence" ? <Evidence analytics={data.analytics} selectors={data.selectors} usage={data.usage} meta={data.meta} /> : null}
      {view === "setup" ? <Setup projects={data.projects} runners={data.runners} onCreateProject={actions.createProject} onCreateEnvironment={actions.createEnvironment} onCreateRunner={actions.createRunner} /> : null}
      {view === "admin" ? <Admin auth={auth} me={data.me} meta={data.meta} apiKeys={data.keys} teamUsers={data.users} onCreateKey={actions.createKey} onInvite={actions.invite} /> : null}
    </Shell>
  );
}
