#!/usr/bin/env python3
"""
atl_run.py — single-line runner for the Atlassian toolkit functions.

Why this exists: agent harnesses that drive smaller local models often flatten
multi-line `python -c "..."` blocks into one line (newlines become spaces),
which breaks the import statements. This runner reduces every call to a single,
flat, whitespace-robust command:

    ATL_PY atl_run.py <function> key=value key=value ...

Examples:
    .venv/bin/python atl_run.py jira_get_issue issue_key=THCU-2473 fields=summary,status
    .venv/bin/python atl_run.py jira_search jql="project = THCU" limit=10
    .venv/bin/python atl_run.py confluence_get_page page_id=711175148

Credentials: loaded from $ATL_ENV if set, else
~/.pi/agent/secrets/atlassian.env, else the process environment.

Value coercion: bare integers -> int, true/false -> bool, everything else stays
a string. Use key="..." to force a string. Commas are NOT split (fields lists
are passed through as-is, which is what the toolkit expects).
"""
import os
import sys
import json
import importlib
import pkgutil
import inspect


def _load_env() -> None:
    env_path = os.environ.get("ATL_ENV") or os.path.expanduser(
        "~/.pi/agent/secrets/atlassian.env"
    )
    try:
        from dotenv import load_dotenv
        if os.path.isfile(env_path):
            load_dotenv(env_path)
    except Exception:
        # dotenv missing or env file absent — fall back to process env
        pass


def _build_registry() -> dict:
    """Map every public function in scripts/*.py to its callable."""
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    import scripts  # noqa: F401  (package marker)

    registry = {}
    pkg_path = os.path.join(here, "scripts")
    for mod in pkgutil.iter_modules([pkg_path]):
        if mod.name.startswith("_"):
            continue
        try:
            m = importlib.import_module(f"scripts.{mod.name}")
        except Exception:
            continue
        for name, fn in inspect.getmembers(m, inspect.isfunction):
            if name.startswith("_"):
                continue
            # first definition wins; functions are uniquely named across modules
            registry.setdefault(name, fn)
    return registry


def _coerce(value: str):
    low = value.lower()
    if low in ("true", "false"):
        return low == "true"
    if value.lstrip("-").isdigit():
        return int(value)
    return value


def _parse_kwargs(args) -> dict:
    kwargs = {}
    for a in args:
        if "=" not in a:
            raise SystemExit(f"bad arg (expected key=value): {a!r}")
        key, _, val = a.partition("=")
        kwargs[key] = _coerce(val)
    return kwargs


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0

    fn_name = sys.argv[1]
    kwargs = _parse_kwargs(sys.argv[2:])

    _load_env()
    registry = _build_registry()

    fn = registry.get(fn_name)
    if fn is None:
        avail = ", ".join(sorted(registry))
        print(json.dumps({
            "success": False,
            "error": f"unknown function {fn_name!r}",
            "available": avail,
        }, indent=2))
        return 1

    result = fn(**kwargs)
    # Toolkit functions usually return JSON strings already; print as-is.
    if isinstance(result, (dict, list)):
        print(json.dumps(result, indent=2))
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
