"""
DOM heuristic healer with confidence scoring.

Returns (element_dict | None, score: int).

Scoring weights:
  id / name / data-testid  → +3
  aria-label / placeholder → +2
  text / class             → +1

CONFIDENCE_THRESHOLD = 3
  score >= 3 → trust DOM, skip LLM
  score <  3 → invoke LLM (tune lower to exercise LLM more often)
"""

from core.logger import log

CONFIDENCE_THRESHOLD = 3

_INTENT_MAP = {
    "username":    ["user-name", "user_name", "username", "email", "uname", "account"],
    "password":    ["password", "pass", "pwd", "secret"],
    "login":       ["login-button", "login_button", "login", "signin", "submit"],
    "logout":      ["logout", "signout"],
    "add to cart": ["add-to-cart", "add_to_cart", "addtocart",
                    "add-backpack", "add-bike", "add-jacket", "add-onesie", "add-bolt"],
    # "continue" must come BEFORE "checkout" — intent "continue button on checkout form"
    # contains both words; first match wins
    "continue":    ["continue"],
    "checkout":    ["checkout"],
    "first name":  ["first-name", "first_name", "firstname", "fname"],
    "last name":   ["last-name", "last_name", "lastname", "lname"],
    "postal":      ["postal-code", "postal_code", "postcode", "zipcode", "zip"],
    "cart":        ["shopping_cart_link", "shopping-cart", "cart"],
    "search":      ["search", "query", "find"],
}

_WEIGHTS = {
    "id": 3, "name": 3, "data_test": 3, "data_testid": 3,
    "aria_label": 2, "placeholder": 2,
    "text": 1, "class": 1,
}


def dom_heal(context: list, intent: str, ctx=None) -> tuple:
    """Returns (best_element | None, confidence_score)."""
    # Find matching keyword list for this intent
    keywords = []
    intent_low = intent.lower()
    for key, kws in _INTENT_MAP.items():
        if key in intent_low:
            keywords = kws
            break

    if not keywords:
        log("DOM", f"No keyword map for intent: '{intent}'", ctx=ctx)
        return None, 0

    best_el, best_score = None, 0
    for el in context:
        score = 0
        for attr, weight in _WEIGHTS.items():
            val = (el.get(attr) or "").lower().replace(" ", "-")
            if any(kw in val for kw in keywords):
                score += weight
        if score > best_score:
            best_score, best_el = score, el

    if best_el:
        confident = best_score >= CONFIDENCE_THRESHOLD
        log("DOM",
            f"id={best_el.get('id')} score={best_score}/{CONFIDENCE_THRESHOLD} "
            f"{'✅ confident' if confident else '⚠ low confidence → LLM'}",
            ctx=ctx)
    else:
        log("DOM", "No candidate found", ctx=ctx)

    return best_el, best_score
