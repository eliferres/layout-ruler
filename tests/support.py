"""Shared helpers: judge a recorded probe from tests/fixtures with no browser.

Each fixture is an HTML page plus the probe JSON recorded from it at
1280x900 (`<name>.json`) and, for a few, at 375x812 (`<name>-375.json`).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from layout_ruler.judge import Scale, judge_viewport

FIXTURES = Path(__file__).parent / "fixtures"


def probe(name: str) -> Dict[str, Any]:
    with open(FIXTURES / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def rows(d: Any, scale: Scale = 4, screen: bool = False) -> List[Dict[str, str]]:
    """The table rows for a fixture name or an (edited) probe dict."""
    d = probe(d) if isinstance(d, str) else d
    return judge_viewport(d, scale, screen)[0]


def failing(d: Any, scale: Scale = 4, screen: bool = False) -> List[str]:
    """The sorted, distinct rules that FAIL."""
    return sorted({r["rule"] for r in rows(d, scale, screen) if r["verdict"] == "FAIL"})


def find(table: List[Dict[str, str]], rule: str, verdict: str, starts: str = "") -> Optional[Dict[str, str]]:
    """The first row of a rule and verdict whose measurement starts with `starts`."""
    return next((r for r in table if r["rule"] == rule and r["verdict"] == verdict
                 and r["measurement"].startswith(starts)), None)


def edited(name: str) -> Dict[str, Any]:
    """A deep copy of a fixture's probe, for a test that moves a box."""
    return copy.deepcopy(probe(name))
