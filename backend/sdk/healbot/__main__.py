"""Healbot SDK command line helpers."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

from healbot.config import (
    DEFAULT_API_URL,
    load_profile,
    profile_path,
    resolve_api_key,
    resolve_api_url,
    save_profile,
)


def _get_json(url: str, api_key: str = "") -> tuple[int, dict]:
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except Exception:
            return exc.code, {"detail": body}


def configure(args: argparse.Namespace) -> int:
    path = save_profile(
        api_key=args.api_key,
        api_url=args.api_url,
        dashboard_url=args.dashboard_url or "",
    )
    print(f"Healbot profile saved: {path}")
    return 0


def show_config(_: argparse.Namespace) -> int:
    profile = load_profile()
    print(f"Profile path: {profile_path()}")
    if not profile:
        print("No profile found.")
        return 1
    safe = dict(profile)
    if safe.get("api_key"):
        safe["api_key"] = safe["api_key"][:12] + "..."
    print(json.dumps(safe, indent=2))
    return 0


def doctor(_: argparse.Namespace) -> int:
    api_url = resolve_api_url()
    api_key = resolve_api_key()
    print(f"Profile path: {profile_path()}")
    print(f"API URL: {api_url}")
    print(f"API key: {'found' if api_key else 'missing'}")

    status, health = _get_json(f"{api_url}/health")
    if status != 200 or health.get("status") != "ok":
        print(f"API health failed: HTTP {status} {health}")
        return 1
    print(f"API health: ok ({health.get('product', 'Healbot')})")

    if api_key:
        auth_status, auth_body = _get_json(f"{api_url}/batches?limit=1", api_key)
        if auth_status == 200:
            print("Authentication: ok")
            return 0
        print(f"Authentication failed: HTTP {auth_status} {auth_body.get('detail', auth_body)}")
        return 1

    print("Authentication: skipped because no API key is configured.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="healbot", description="Healbot SDK utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    configure_parser = sub.add_parser("configure", help="Persist a local Healbot profile")
    configure_parser.add_argument("--api-key", required=True, help="Healbot API key")
    configure_parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Healbot API URL")
    configure_parser.add_argument("--dashboard-url", default="", help="Dashboard URL")
    configure_parser.set_defaults(func=configure)

    show_parser = sub.add_parser("show-config", help="Show the active local profile")
    show_parser.set_defaults(func=show_config)

    doctor_parser = sub.add_parser("doctor", help="Check API connectivity and authentication")
    doctor_parser.set_defaults(func=doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
