from bs4 import BeautifulSoup
from core.logger import log


def extract_element_context(html: str, ctx=None) -> list:
    """Parse page HTML → list of identifiable element dicts."""
    if not html:
        log("CONTEXT", "Empty HTML", level="warning", ctx=ctx)
        return []

    soup = BeautifulSoup(html, "html.parser")
    elements = []

    for tag in soup.find_all(["input", "button", "select", "textarea", "a"]):
        el = {
            "tag":         tag.name,
            "id":          tag.get("id"),
            "name":        tag.get("name"),
            "type":        tag.get("type"),
            "placeholder": tag.get("placeholder"),
            "aria_label":  tag.get("aria-label"),
            "data_test":   tag.get("data-test"),
            "data_testid": tag.get("data-testid"),
            "role":        tag.get("role"),
            "class":       " ".join(tag.get("class", [])) or None,
            "text":        tag.text.strip() or None,
        }
        # Only keep elements that have at least one identifiable attribute
        if any([el["id"], el["name"], el["data_test"], el["data_testid"],
                el["aria_label"], el["text"], el["placeholder"]]):
            elements.append(el)

    log("CONTEXT", f"{len(elements)} elements extracted", ctx=ctx)
    return elements
