"""
Selenium adapter for Healbot.

Patches Selenium WebDriver at the class level so existing tests do not need
wrappers. It streams lightweight step events and screenshots to the dashboard
and attempts selector healing when lookup fails.
"""
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By


def _locator_label(by, value):
    return f"{by}={value}"


def _to_xpath(by, value):
    mapping = {
        "id": "//*[@id='" + value + "']",
        "name": "//*[@name='" + value + "']",
        "class name": "//*[contains(@class,'" + value + "')]",
        "tag name": "//" + value,
        "link text": "//a[normalize-space()='" + value + "']",
        "partial link text": "//a[contains(text(),'" + value + "')]",
        "css selector": value,
        "xpath": value,
    }
    return mapping.get(by, value)


class SeleniumAdapter:
    def __init__(self, hb):
        self._hb = hb
        self._orig_find = None
        self._orig_finds = None

    def patch(self):
        from selenium.webdriver.remote.webdriver import WebDriver

        hb = self._hb
        orig_find = WebDriver.find_element
        orig_finds = WebDriver.find_elements

        self._orig_find = orig_find
        self._orig_finds = orig_finds

        def healed_find_element(driver_self, by, value):
            hb.start_live_stream(driver_self)
            selector_label = _locator_label(by, value)
            test_name = getattr(hb, "_current_test", "")
            try:
                element = orig_find(driver_self, by, value)
                hb.stream_lookup(
                    driver_self,
                    status="pass",
                    selector=selector_label,
                    description=test_name or f"Located {selector_label}",
                )
                return element
            except NoSuchElementException as original_err:
                failed_selector = _to_xpath(by, value)
                print(f"\n[HealBot] Selector failed: ({by}, '{value}') - healing...")
                hb.stream_lookup(
                    driver_self,
                    status="healing",
                    selector=failed_selector,
                    description=test_name or f"Healing {selector_label}",
                    force=True,
                )
                healed = hb.heal(
                    selector=failed_selector,
                    html=driver_self.page_source,
                    test_name=test_name,
                )
                if healed:
                    try:
                        element = orig_find(driver_self, By.XPATH, healed)
                        heal_resp = getattr(hb, "_last_heal_response", {}) or {}
                        hb.stream_lookup(
                            driver_self,
                            status="healed",
                            selector=failed_selector,
                            description=test_name or f"Healed {selector_label}",
                            force=True,
                            healed_selector=healed,
                            strategy=heal_resp.get("strategy", ""),
                            llm_used=bool(heal_resp.get("llm_used")),
                        )
                        return element
                    except NoSuchElementException:
                        print(f"[HealBot] Healed selector also failed: {healed}")

                hb.stream_lookup(
                    driver_self,
                    status="fail",
                    selector=failed_selector,
                    description=test_name or f"Could not heal {selector_label}",
                    force=True,
                )
                raise original_err

        def healed_find_elements(driver_self, by, value):
            hb.start_live_stream(driver_self)
            elements = orig_finds(driver_self, by, value)
            if elements:
                return elements

            selector_label = _locator_label(by, value)
            failed_selector = _to_xpath(by, value)
            test_name = getattr(hb, "_current_test", "")
            print(f"\n[HealBot] find_elements empty: ({by}, '{value}') - healing...")
            hb.stream_lookup(
                driver_self,
                status="healing",
                selector=failed_selector,
                description=test_name or f"Healing list {selector_label}",
                force=True,
            )
            healed = hb.heal(
                selector=failed_selector,
                html=driver_self.page_source,
                test_name=test_name,
            )
            if healed:
                healed_list = orig_finds(driver_self, By.XPATH, healed)
                if healed_list:
                    heal_resp = getattr(hb, "_last_heal_response", {}) or {}
                    hb.stream_lookup(
                        driver_self,
                        status="healed",
                        selector=failed_selector,
                        description=test_name or f"Healed list {selector_label}",
                        force=True,
                        healed_selector=healed,
                        strategy=heal_resp.get("strategy", ""),
                        llm_used=bool(heal_resp.get("llm_used")),
                    )
                    return healed_list
            return elements

        WebDriver.find_element = healed_find_element
        WebDriver.find_elements = healed_find_elements
        print("[HealBot] Selenium patched - find_element is now self-healing")

    def unpatch(self):
        from selenium.webdriver.remote.webdriver import WebDriver

        if self._orig_find is not None:
            WebDriver.find_element = self._orig_find
            WebDriver.find_elements = self._orig_finds
            self._orig_find = None
            self._orig_finds = None
            print("[HealBot] Selenium unpatched - find_element restored")
