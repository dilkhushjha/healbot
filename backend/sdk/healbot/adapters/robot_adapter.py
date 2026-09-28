"""
robot_adapter.py

Robot Framework adapter.

Robot Framework uses SeleniumLibrary which uses Selenium under the hood.
Rather than patching Robot's keyword layer, we patch Selenium's WebDriver
class directly — so the heal happens at the Selenium level, transparently.

Additionally provides:
  - HealBotListener: attach with --listener for auto session management
  - HealBotLibrary:  import in .robot files for explicit healing keywords
"""
import os


class RobotAdapter:
    """
    Patches WebDriver via the SeleniumAdapter.
    Works for any Robot Framework + SeleniumLibrary project.
    """

    def __init__(self, hb):
        self._hb = hb
        self._adapter = None

    def patch(self):
        # Import inline to avoid circular / absolute import issues
        import sys
        import os
        _here = os.path.dirname(os.path.abspath(__file__))
        if _here not in sys.path:
            sys.path.insert(0, _here)

        # Use a local import of selenium_adapter from the same package directory
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "selenium_adapter",
            os.path.join(_here, "selenium_adapter.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self._adapter = module.SeleniumAdapter(self._hb)
        self._adapter.patch()
        print("[HealBot] Robot Framework: patched via Selenium WebDriver")

    def unpatch(self):
        if self._adapter:
            self._adapter.unpatch()
            self._adapter = None


class HealBotListener:
    """
    Robot Framework v3 listener.
    Attach with:  robot --listener healbot.adapters.robot_adapter.HealBotListener tests/

    Automatically starts a session at suite start and ends it at suite end.
    """

    ROBOT_LISTENER_API_VERSION = 3

    def __init__(self):
        from healbot.client import HealBot
        self._hb = HealBot()
        self._adapter = RobotAdapter(self._hb)

    def start_suite(self, data, result):
        self._adapter.patch()
        self._hb.start_session(name=data.name, framework="robot")

    def end_suite(self, data, result):
        report = self._hb.session_report()
        print("\n[HealBot] Suite complete — healed=%d failed=%d heal_rate=%s%%"
              % (report["total_heals"], report["total_failures"], report["heal_rate"]))
        self._hb.end_session()
        self._adapter.unpatch()


class HealBotLibrary:
    """
    Robot Framework keyword library.
    Import in your .robot file:
        Library    healbot.adapters.robot_adapter.HealBotLibrary

    Available keywords:
        Start Heal Session    [name]
        End Heal Session
        Heal Selector         <selector>    <html>
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self):
        from healbot.client import HealBot
        self._hb = HealBot()

    def start_heal_session(self, name="Robot Run"):
        return self._hb.start_session(name=name, framework="robot")

    def end_heal_session(self):
        return self._hb.end_session()

    def heal_selector(self, broken_selector, page_html=""):
        healed = self._hb.heal(broken_selector, page_html)
        return healed if healed else broken_selector
