"""Shared runner capability definitions, health checks, and execution checks."""
import os
import shutil

from sqlalchemy import select

from core.database import runner_capabilities


SYSTEM_CAPABILITIES = [
    {
        "id": "local-selenium-chrome",
        "name": "Local Selenium Chrome",
        "provider": "local",
        "framework": "selenium",
        "browser": "chrome",
        "browser_version": "stable",
        "platform": "web",
        "os": "local",
        "device": "",
        "viewport": "desktop",
        "region": "local",
        "concurrency": 1,
        "status": "available",
        "tags": ["default", "local", "selenium"],
        "scope": "system",
        "is_active": True,
    },
    {
        "id": "local-playwright-chromium",
        "name": "Local Playwright Chromium",
        "provider": "local",
        "framework": "playwright",
        "browser": "chromium",
        "browser_version": "bundled",
        "platform": "web",
        "os": "local",
        "device": "",
        "viewport": "desktop",
        "region": "local",
        "concurrency": 1,
        "status": "planned",
        "tags": ["local", "playwright"],
        "scope": "system",
        "is_active": True,
    },
    {
        "id": "cloud-chrome-grid",
        "name": "Cloud Chrome Grid",
        "provider": "cloud",
        "framework": "selenium",
        "browser": "chrome",
        "browser_version": "latest",
        "platform": "web",
        "os": "linux",
        "device": "",
        "viewport": "desktop",
        "region": "auto",
        "concurrency": 5,
        "status": "planned",
        "tags": ["cloud-ready", "grid"],
        "scope": "system",
        "is_active": True,
    },
    {
        "id": "mobile-android-chrome",
        "name": "Android Chrome Device",
        "provider": "cloud",
        "framework": "appium",
        "browser": "chrome",
        "browser_version": "latest",
        "platform": "android",
        "os": "android",
        "device": "generic-phone",
        "viewport": "mobile",
        "region": "auto",
        "concurrency": 2,
        "status": "planned",
        "tags": ["cloud-ready", "mobile", "appium"],
        "scope": "system",
        "is_active": True,
    },
]


def system_capability(capability_id: str) -> dict | None:
    for capability in SYSTEM_CAPABILITIES:
        if capability["id"] == capability_id:
            return dict(capability)
    return None


def tenant_capability(conn, tenant_id: str, capability_id: str) -> dict | None:
    row = conn.execute(
        select(runner_capabilities).where(
            runner_capabilities.c.id == capability_id,
            runner_capabilities.c.tenant_id == tenant_id,
            runner_capabilities.c.is_active == True,
        )
    ).mappings().first()
    if not row:
        return None
    item = dict(row)
    item["scope"] = "tenant"
    item["tags"] = item.get("tags") or []
    return item


def resolve_capability(conn, tenant_id: str, capability_id: str) -> dict | None:
    if not capability_id:
        return None
    return system_capability(capability_id) or tenant_capability(conn, tenant_id, capability_id)


def default_capability() -> dict:
    return dict(SYSTEM_CAPABILITIES[0])


def _first_existing(paths: list[str]) -> str:
    for path in paths:
        if path and os.path.exists(path):
            return path
    return ""


def _browser_path(browser: str) -> str:
    browser = browser or "chrome"
    candidates = {
        "chrome": [
            shutil.which("chrome"),
            shutil.which("google-chrome"),
            shutil.which("chrome.exe"),
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ],
        "chromium": [
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
            shutil.which("chrome"),
            shutil.which("chrome.exe"),
        ],
        "firefox": [
            shutil.which("firefox"),
            shutil.which("firefox.exe"),
            os.path.expandvars(r"%ProgramFiles%\Mozilla Firefox\firefox.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"),
        ],
        "edge": [
            shutil.which("msedge"),
            shutil.which("msedge.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ],
    }
    return _first_existing(candidates.get(browser, []))


def _driver_hint(browser: str) -> str:
    drivers = {
        "chrome": ["chromedriver", "chromedriver.exe"],
        "chromium": ["chromedriver", "chromedriver.exe"],
        "firefox": ["geckodriver", "geckodriver.exe"],
        "edge": ["msedgedriver", "msedgedriver.exe"],
    }
    for executable in drivers.get(browser or "chrome", []):
        path = shutil.which(executable)
        if path:
            return path
    return "selenium-manager"


def capability_health(capability: dict | None) -> dict:
    capability = capability or default_capability()
    runnable, reason = execution_status(capability, check_health=False)
    if not runnable:
        return {
            "status": "planned" if capability.get("status") == "planned" else "blocked",
            "ready": False,
            "reason": reason,
            "browser_path": "",
            "driver": "",
        }

    browser = capability.get("browser", "chrome")
    browser_path = _browser_path(browser)
    if not browser_path:
        return {
            "status": "missing",
            "ready": False,
            "reason": f"Browser '{browser}' was not found on this machine",
            "browser_path": "",
            "driver": "",
        }

    driver = _driver_hint(browser)
    return {
        "status": "ready",
        "ready": True,
        "reason": "Runner prerequisites detected",
        "browser_path": browser_path,
        "driver": driver,
    }


def execution_status(capability: dict | None, check_health: bool = True) -> tuple[bool, str]:
    capability = capability or default_capability()
    if capability.get("status") != "available":
        return False, f"Runner capability '{capability.get('name')}' is {capability.get('status', 'unavailable')}"
    if capability.get("provider") not in {"local", "self-hosted"}:
        return False, f"Runner provider '{capability.get('provider')}' is not connected yet"
    if capability.get("framework") != "selenium":
        return False, f"Runner framework '{capability.get('framework')}' is not executable yet"
    if capability.get("platform") != "web":
        return False, f"Runner platform '{capability.get('platform')}' is not executable yet"
    if capability.get("browser") not in {"chrome", "chromium", "firefox", "edge"}:
        return False, f"Runner browser '{capability.get('browser')}' is not executable yet"
    if check_health:
        health = capability_health(capability)
        if not health.get("ready"):
            return False, health.get("reason", "Runner is not ready")
    return True, ""
