"""Selenium WebDriver factory for Healbot runner capabilities."""
import os
import sys

from core.logger import log
from selenium import webdriver


_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def _capability_name(capability: dict | None) -> str:
    if not capability:
        return "Local Selenium Chrome"
    return capability.get("name") or capability.get("id") or "runner"


def _assert_executable(capability: dict | None):
    if not capability:
        return

    status = capability.get("status", "available")
    provider = capability.get("provider", "local")
    framework = capability.get("framework", "selenium")
    platform = capability.get("platform", "web")
    browser = capability.get("browser", "chrome")

    if status != "available":
        raise RuntimeError(f"Runner capability '{_capability_name(capability)}' is {status}")
    if provider not in {"local", "self-hosted"}:
        raise RuntimeError(f"Runner provider '{provider}' is not connected yet")
    if framework != "selenium":
        raise RuntimeError(f"Runner framework '{framework}' is not executable yet")
    if platform != "web":
        raise RuntimeError(f"Runner platform '{platform}' is not executable yet")
    if browser not in {"chrome", "chromium", "firefox", "edge"}:
        raise RuntimeError(f"Runner browser '{browser}' is not executable yet")


def _headless_enabled(headless: bool) -> bool:
    return headless or os.environ.get("HEALBOT_HEADLESS") == "1"


def _common_options(options, headless: bool):
    options.add_argument("--log-level=3")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    if _headless_enabled(headless):
        options.add_argument("--headless=new")
    return options


def get_driver(headless: bool = False, ctx=None, capability: dict | None = None):
    _assert_executable(capability)
    browser = (capability or {}).get("browser", "chrome")

    if browser in {"chrome", "chromium"}:
        from selenium.webdriver.chrome.options import Options
        driver = webdriver.Chrome(options=_common_options(Options(), headless))
    elif browser == "firefox":
        from selenium.webdriver.firefox.options import Options
        options = Options()
        if _headless_enabled(headless):
            options.add_argument("-headless")
        driver = webdriver.Firefox(options=options)
    elif browser == "edge":
        from selenium.webdriver.edge.options import Options
        driver = webdriver.Edge(options=_common_options(Options(), headless))
    else:
        raise RuntimeError(f"Unsupported runner browser: {browser}")

    driver.maximize_window()
    log("DRIVER", f"{_capability_name(capability)} initialised", ctx=ctx)
    return driver
