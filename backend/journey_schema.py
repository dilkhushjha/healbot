"""
Validates and normalises client-submitted journey JSON before queuing.

Journey JSON schema:
{
  "name":      "My App Login",         // required
  "client_id": "acme",                 // optional — used for custom intent maps
  "base_url":  "https://myapp.com",    // optional — prepended to relative step URLs
  "steps": [
    {
      "id":          "login",          // required, unique
      "description": "Click login",   // required
      "url":         "/login",         // optional
      "action":      "click",          // required: click | type | wait | assert_url
      "selector":    "//button[@id='x']", // required (except assert_url)
      "value":       null,             // required for type and assert_url
      "intent":      "login button",   // optional — overrides auto-detection
      "critical":    true              // optional, default false
    }
  ]
}
"""

VALID_ACTIONS = {"click", "type", "wait", "assert_url"}


def validate(journey: dict) -> tuple:
    """Returns (is_valid: bool, error_message: str)."""
    if not isinstance(journey, dict):
        return False, "Journey must be a JSON object"
    if not journey.get("name"):
        return False, "Journey must have a 'name'"
    steps = journey.get("steps")
    if not steps or not isinstance(steps, list):
        return False, "Journey must have a non-empty 'steps' array"

    seen = set()
    for i, step in enumerate(steps):
        p = f"Step {i+1}"
        if not step.get("id"):
            return False, f"{p}: missing 'id'"
        if step["id"] in seen:
            return False, f"{p}: duplicate id '{step['id']}'"
        seen.add(step["id"])
        if not step.get("description"):
            return False, f"{p} ({step['id']}): missing 'description'"
        if step.get("action") not in VALID_ACTIONS:
            return False, f"{p} ({step['id']}): action must be one of {VALID_ACTIONS}"
        if step["action"] != "assert_url" and not step.get("selector"):
            return False, f"{p} ({step['id']}): 'selector' required for '{step['action']}'"
        if step["action"] in ("type", "assert_url") and step.get("value") is None:
            return False, f"{p} ({step['id']}): 'value' required for '{step['action']}'"

    return True, ""


def normalise(journey: dict) -> dict:
    """Fill defaults so downstream code never needs to null-check optional fields."""
    base = journey.get("base_url", "")
    steps = []
    for s in journey["steps"]:
        url = s.get("url")
        if url and base and not url.startswith("http"):
            url = base.rstrip("/") + "/" + url.lstrip("/")
        steps.append({
            "id":          s["id"],
            "description": s["description"],
            "url":         url,
            "action":      s["action"],
            "selector":    s.get("selector"),
            "value":       s.get("value"),
            "intent":      s.get("intent"),     # None = auto-detect
            "critical":    s.get("critical", False),
        })
    return {
        "name":      journey["name"],
        "client_id": journey.get("client_id"),
        "base_url":  base,
        "steps":     steps,
    }
