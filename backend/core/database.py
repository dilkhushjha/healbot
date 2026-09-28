"""
database.py — Multi-tenant SQLAlchemy schema.

Tables:
  tenants         — organisations (clients)
  api_keys        — auth tokens per tenant
  projects        — logical grouping of scripts per tenant
  batches         — one batch = one submission of N scripts
  script_runs     — individual script execution within a batch
  heal_events     — one row per healing attempt within a script run
  step_results    — one row per journey step within a script run
  intent_maps     — client-registered custom keyword→intent mappings
  usage_log       — daily usage counters per tenant (for billing)
"""

import os
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, MetaData, Table, Column,
    String, Integer, DateTime, Text, Boolean, Float, JSON,
    select, update, func, text
)
from core.config import DB_URL

# SQLite is useful for local development; hosted deployments should set a
# persistent PostgreSQL URL via HEALBOT_DB_URL.
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
if DB_URL.startswith("sqlite:///"):
    sqlite_path = DB_URL.removeprefix("sqlite:///").split("?", 1)[0]
    if sqlite_path and sqlite_path != ":memory:" and not sqlite_path.startswith("/"):
        os.makedirs(os.path.dirname(sqlite_path) or ".", exist_ok=True)
engine = create_engine(DB_URL, connect_args=connect_args, pool_pre_ping=True)
metadata = MetaData()

# ── Tenants ───────────────────────────────────────────────────────────────────
tenants = Table("tenants", metadata,
                Column("id",           String,  primary_key=True),
                Column("name",         String,  nullable=False),
                Column("email",        String,  nullable=False, unique=True),
                Column("tier",         String,
                       nullable=False, default="free"),
                Column("created_at",   DateTime),
                Column("is_active",    Boolean, default=True),
                )

api_keys = Table("api_keys", metadata,
                 Column("key",          String,  primary_key=True),
                 Column("tenant_id",    String,  nullable=False),
                 Column("name",         String,
                        nullable=False, default="default"),
                 Column("created_at",   DateTime),
                 Column("last_used_at", DateTime, nullable=True),
                 Column("is_active",    Boolean, default=True),
                 )

tenant_users = Table("tenant_users", metadata,
                     Column("id",         String, primary_key=True),
                     Column("tenant_id",  String, nullable=False),
                     Column("email",      String, nullable=False),
                     Column("name",       String, nullable=False),
                     Column("role",       String, nullable=False, default="viewer"),
                     Column("status",     String, nullable=False, default="invited"),
                     Column("created_at", DateTime),
                     Column("updated_at", DateTime, nullable=True),
                     Column("is_active",  Boolean, default=True),
                     )

audit_events = Table("audit_events", metadata,
                     Column("id",         String, primary_key=True),
                     Column("tenant_id",  String, nullable=False),
                     Column("actor",      String, nullable=True),
                     Column("action",     String, nullable=False),
                     Column("target",     String, nullable=True),
                     Column("details",    JSON, nullable=True),
                     Column("created_at", DateTime),
                     )

runner_capabilities = Table("runner_capabilities", metadata,
                            Column("id",              String, primary_key=True),
                            Column("tenant_id",       String, nullable=False),
                            Column("name",            String, nullable=False),
                            Column("provider",        String, nullable=False, default="local"),
                            Column("framework",       String, nullable=False, default="selenium"),
                            Column("browser",         String, nullable=False, default="chrome"),
                            Column("browser_version", String, nullable=True),
                            Column("platform",        String, nullable=False, default="web"),
                            Column("os",              String, nullable=True),
                            Column("device",          String, nullable=True),
                            Column("viewport",        String, nullable=True),
                            Column("region",          String, nullable=True),
                            Column("concurrency",     Integer, default=1),
                            Column("status",          String, nullable=False, default="available"),
                            Column("tags",            JSON, nullable=True),
                            Column("created_at",      DateTime),
                            Column("updated_at",      DateTime, nullable=True),
                            Column("is_active",       Boolean, default=True),
                            )

# ── Projects ──────────────────────────────────────────────────────────────────
projects = Table("projects", metadata,
                 Column("id",           String,  primary_key=True),
                 Column("tenant_id",    String,  nullable=False),
                 Column("name",         String,  nullable=False),
                 Column("description",  Text,    nullable=True),
                 Column("created_at",   DateTime),
                 )

environments = Table("environments", metadata,
                     Column("id",          String, primary_key=True),
                     Column("tenant_id",   String, nullable=False),
                     Column("project_id",  String, nullable=False),
                     Column("name",        String, nullable=False),
                     Column("base_url",    Text, nullable=True),
                     Column("framework",   String, nullable=False, default="playwright"),
                     Column("browser",     String, nullable=False, default="chromium"),
                     Column("platform",    String, nullable=False, default="web"),
                     Column("runner_capability_id", String, nullable=True),
                     Column("variables",   JSON, nullable=True),
                     Column("created_at",  DateTime),
                     Column("updated_at",  DateTime, nullable=True),
                     Column("is_active",   Boolean, default=True),
                     )

# ── Batches ───────────────────────────────────────────────────────────────────
batches = Table("batches", metadata,
                Column("id",              String,  primary_key=True),
                Column("tenant_id",       String,  nullable=False),
                Column("project_id",      String,  nullable=True),
                Column("environment_id",  String,  nullable=True),
                Column("environment_snapshot", JSON, nullable=True),
                Column("name",            String,  nullable=False),
                Column("status",          String,
                       nullable=False, default="queued"),
                # queued | running | completed | failed | cancelled
                Column("total_scripts",   Integer, default=0),
                Column("completed",       Integer, default=0),
                Column("passed",          Integer, default=0),
                Column("healed",          Integer, default=0),
                Column("failed",          Integer, default=0),
                Column("created_at",      DateTime),
                Column("started_at",      DateTime, nullable=True),
                Column("finished_at",     DateTime, nullable=True),
                # "sdk" | "api" | "dashboard"
                Column("submitted_by",    String,  nullable=True),
                )

# ── Script Runs ───────────────────────────────────────────────────────────────
script_runs = Table("script_runs", metadata,
                    Column("id",             String,  primary_key=True),
                    Column("batch_id",       String,  nullable=False),
                    Column("tenant_id",      String,  nullable=False),
                    Column("script_name",    String,  nullable=False),
                    # position in batch
                    Column("script_index",   Integer, default=0),
                    Column("status",         String,
                           nullable=False, default="queued"),
                    # queued | running | passed | failed | healed | error
                    Column("total_steps",    Integer, default=0),
                    Column("passed_steps",   Integer, default=0),
                    Column("healed_steps",   Integer, default=0),
                    Column("failed_steps",   Integer, default=0),
                    Column("llm_calls",      Integer, default=0),
                    Column("vision_calls",   Integer, default=0),
                    Column("duration_ms",    Float,   nullable=True),
                    Column("error",          Text,    nullable=True),
                    # full journey snapshot
                    Column("journey_def",    JSON,    nullable=True),
                    Column("created_at",     DateTime),
                    Column("started_at",     DateTime, nullable=True),
                    Column("finished_at",    DateTime, nullable=True),
                    )

# ── Step Results ──────────────────────────────────────────────────────────────
step_results = Table("step_results", metadata,
                     Column("id",                String,
                            primary_key=True),  # run_id:step_id
                     Column("run_id",            String,  nullable=False),
                     Column("tenant_id",         String,  nullable=False),
                     Column("step_id",           String,  nullable=False),
                     Column("description",       String,  nullable=True),
                     Column("action",            String,  nullable=True),
                     Column("original_selector", Text,    nullable=True),
                     Column("healed_selector",   Text,    nullable=True),
                     Column("status",            String,
                            nullable=False, default="pending"),
                     Column("strategy",          String,  nullable=True),
                     Column("duration_ms",       Float,   nullable=True),
                     Column("error",             Text,    nullable=True),
                     Column("screenshot_path",   Text,    nullable=True),
                     Column("vision_verdict",    String,  nullable=True),
                     Column("vision_note",       Text,    nullable=True),
                     Column("started_at",        DateTime, nullable=True),
                     Column("finished_at",       DateTime, nullable=True),
                     )

# ── Heal Events ───────────────────────────────────────────────────────────────
heal_events = Table("heal_events", metadata,
                    Column("id",             Integer,
                           primary_key=True, autoincrement=True),
                    Column("run_id",         String,  nullable=False),
                    Column("tenant_id",      String,  nullable=False),
                    Column("step_id",        String,  nullable=False),
                    Column("selector",       Text,    nullable=False),
                    Column("intent",         String,  nullable=True),
                    Column("dom_score",      Integer, nullable=True),
                    Column("dom_candidate",  Text,    nullable=True),
                    Column("llm_invoked",    Boolean, default=False),
                    Column("llm_candidate",  Text,    nullable=True),
                    Column("final_selector", Text,    nullable=True),
                    Column("strategy",       String,  nullable=True),
                    Column("success",        Boolean, default=False),
                    Column("created_at",     DateTime),
                    )

# ── Intent Maps ───────────────────────────────────────────────────────────────
intent_maps = Table("intent_maps", metadata,
                    Column("tenant_id",  String, primary_key=True),
                    Column("mappings",   JSON,   nullable=False),
                    Column("updated_at", DateTime),
                    )

# ── Usage Log ─────────────────────────────────────────────────────────────────
usage_log = Table("usage_log", metadata,
                  Column("id",           Integer,
                         primary_key=True, autoincrement=True),
                  Column("tenant_id",    String,  nullable=False),
                  Column("date",         String,
                         nullable=False),  # YYYY-MM-DD
                  Column("scripts_run",  Integer, default=0),
                  Column("heals",        Integer, default=0),
                  Column("llm_calls",    Integer, default=0),
                  )

metadata.create_all(engine)


def _ensure_local_schema():
    """Add lightweight SQLite columns for existing local installations."""
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as conn:
        batch_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(batches)")).fetchall()
        }
        environment_columns = {
            row[1] for row in conn.execute(text("PRAGMA table_info(environments)")).fetchall()
        }
    batch_additions = {
        "environment_id": "ALTER TABLE batches ADD COLUMN environment_id VARCHAR",
        "environment_snapshot": "ALTER TABLE batches ADD COLUMN environment_snapshot JSON",
    }
    environment_additions = {
        "runner_capability_id": "ALTER TABLE environments ADD COLUMN runner_capability_id VARCHAR",
    }
    with engine.begin() as conn:
        for name, statement in batch_additions.items():
            if name not in batch_columns:
                conn.execute(text(statement))
        for name, statement in environment_additions.items():
            if name not in environment_columns:
                conn.execute(text(statement))


_ensure_local_schema()


# ── Query helpers ─────────────────────────────────────────────────────────────

def now():
    return datetime.now(timezone.utc)


def actor_for_tenant(tenant: dict) -> dict:
    with engine.connect() as conn:
        user = conn.execute(
            select(tenant_users).where(
                tenant_users.c.tenant_id == tenant["id"],
                tenant_users.c.email == tenant["email"],
                tenant_users.c.is_active == True,
            )
        ).mappings().first()
    if user:
        return dict(user)
    return {
        "id": "",
        "tenant_id": tenant["id"],
        "email": tenant["email"],
        "name": tenant["name"],
        "role": "owner",
        "status": "active",
        "is_active": True,
    }


def upsert_step(run_id: str, step_id: str, tenant_id: str, **kwargs):
    pk = f"{run_id}:{step_id}"
    with engine.begin() as conn:
        exists = conn.execute(select(step_results).where(
            step_results.c.id == pk)).first()
        if exists:
            conn.execute(update(step_results).where(
                step_results.c.id == pk).values(**kwargs))
        else:
            conn.execute(step_results.insert().values(
                id=pk, run_id=run_id, step_id=step_id, tenant_id=tenant_id, **kwargs))


def get_tenant_by_key(api_key: str) -> dict | None:
    with engine.begin() as conn:
        key_row = conn.execute(
            select(api_keys).where(api_keys.c.key ==
                                   api_key, api_keys.c.is_active == True)
        ).mappings().first()
        if not key_row:
            return None
        tenant_row = conn.execute(
            select(tenants).where(tenants.c.id ==
                                  key_row["tenant_id"], tenants.c.is_active == True)
        ).mappings().first()
        if not tenant_row:
            return None
        # Update last_used
        conn.execute(update(api_keys).where(
            api_keys.c.key == api_key).values(last_used_at=now()))
        return dict(tenant_row)


def get_auth_context_by_key(api_key: str) -> dict | None:
    tenant = get_tenant_by_key(api_key)
    if not tenant:
        return None
    actor = actor_for_tenant(tenant)
    return {
        "tenant": tenant,
        "user": actor,
        "role": actor.get("role", "viewer"),
    }


def get_daily_usage(tenant_id: str, date_str: str) -> int:
    with engine.connect() as conn:
        row = conn.execute(
            select(usage_log).where(
                usage_log.c.tenant_id == tenant_id,
                usage_log.c.date == date_str,
            )
        ).mappings().first()
        return row["scripts_run"] if row else 0


def increment_usage(tenant_id: str, date_str: str, scripts: int = 1, heals: int = 0, llm: int = 0):
    with engine.begin() as conn:
        row = conn.execute(
            select(usage_log).where(
                usage_log.c.tenant_id == tenant_id,
                usage_log.c.date == date_str,
            )
        ).first()
        if row:
            conn.execute(
                update(usage_log).where(
                    usage_log.c.tenant_id == tenant_id,
                    usage_log.c.date == date_str,
                ).values(
                    scripts_run=usage_log.c.scripts_run + scripts,
                    heals=usage_log.c.heals + heals,
                    llm_calls=usage_log.c.llm_calls + llm,
                )
            )
        else:
            conn.execute(usage_log.insert().values(
                tenant_id=tenant_id, date=date_str,
                scripts_run=scripts, heals=heals, llm_calls=llm,
            ))


def get_analytics(tenant_id: str, days: int = 30) -> dict:
    """Aggregate stats for dashboard analytics panel."""
    with engine.connect() as conn:
        # Batch stats
        batch_rows = conn.execute(
            select(batches).where(batches.c.tenant_id == tenant_id)
            .order_by(batches.c.created_at.desc()).limit(days * 5)
        ).mappings().all()

        # Heal events
        heal_rows = conn.execute(
            select(heal_events).where(heal_events.c.tenant_id == tenant_id)
            .order_by(heal_events.c.created_at.desc()).limit(1000)
        ).mappings().all()

        # Flakiness: scripts that have both passed and failed across runs
        run_rows = conn.execute(
            select(script_runs).where(script_runs.c.tenant_id == tenant_id)
            .order_by(script_runs.c.created_at.desc()).limit(500)
        ).mappings().all()

    total_scripts = len(run_rows)
    total_heals = sum(1 for h in heal_rows if h["success"])
    total_fails = sum(1 for r in run_rows if r["status"] == "failed")
    heal_rate = round((total_heals / total_scripts * 100)
                      if total_scripts else 0, 1)

    # Strategy breakdown
    strategies = {}
    for h in heal_rows:
        s = h["strategy"] or "unknown"
        strategies[s] = strategies.get(s, 0) + 1

    # Daily trend (last 14 days)
    from collections import defaultdict
    daily: dict = defaultdict(lambda: {"runs": 0, "healed": 0, "failed": 0})
    for r in run_rows:
        if r["created_at"]:
            day = str(r["created_at"])[:10]
            daily[day]["runs"] += 1
            if r["status"] == "healed":
                daily[day]["healed"] += 1
            if r["status"] == "failed":
                daily[day]["failed"] += 1

    return {
        "total_scripts":    total_scripts,
        "total_heals":      total_heals,
        "total_failures":   total_fails,
        "heal_rate_pct":    heal_rate,
        "strategy_breakdown": strategies,
        "daily_trend":      dict(sorted(daily.items())[-14:]),
        "recent_batches":   [dict(b) for b in batch_rows[:10]],
    }
