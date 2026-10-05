"""The layout-ruler command: render a page, measure it, print the verdict.

Exit codes: 0 every rule passed, 1 at least one finding, 2 the page could not
be measured or the command line was wrong.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import __version__
from .chrome import CHROME_ENV, IMAGES_WAIT_MS, SETTLE_CAP_MS, Chrome, MeasureError, find_chrome, measure
from .judge import Allow, Scale, check_probe, judge_viewport

PROG = "layout-ruler"
DEFAULT_VIEWPORTS = [(1280, 900), (375, 812)]
PROBE_FILE = Path(__file__).with_name("probe.js")


class UsageError(Exception):
    """A configuration problem the user can fix; reported in one line, exit 2."""


def parse_viewport(s: str) -> Tuple[int, int]:
    m = re.fullmatch(r"(\d+)x(\d+)", s.strip())
    if not m or not int(m.group(1)) or not int(m.group(2)):
        raise argparse.ArgumentTypeError(f"viewport must be WIDTHxHEIGHT in px, got {s!r}")
    return int(m.group(1)), int(m.group(2))


def parse_scale(s: str) -> frozenset:
    try:
        vals = frozenset(float(round(float(v))) for v in s.split(",") if v.strip())
    except ValueError:
        raise argparse.ArgumentTypeError(f"scale must be px values separated by commas, got {s!r}") from None
    if not vals:
        raise argparse.ArgumentTypeError("scale is empty")
    return vals


def positive_int(s: str) -> int:
    if not s.isdigit() or int(s) == 0:
        raise argparse.ArgumentTypeError(f"must be a whole number of px above 0, got {s!r}")
    return int(s)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=PROG,
        description="Measure the geometry of a rendered web page: column edges, gaps, equal siblings, "
                    "baselines and horizontal overflow, at each viewport width.",
        epilog="exit codes: 0 no findings, 1 findings, 2 could not measure or bad arguments")
    ap.add_argument("page", nargs="?", help="an HTML file, or an http(s):// or file:// URL")
    ap.add_argument("--viewport", action="append", type=parse_viewport, default=[], metavar="WxH",
                    help="a viewport to render at; repeatable (default: 1280x900 and 375x812)")
    ap.add_argument("--screen", action="store_true",
                    help="the page is one screen: it must not scroll vertically either")
    ap.add_argument("--grid", type=positive_int, default=4, metavar="PX",
                    help="gaps must be multiples of this (default: 4)")
    ap.add_argument("--scale", type=parse_scale, metavar="PX,PX,...",
                    help="gaps must be one of these values; replaces --grid")
    ap.add_argument("--chrome", metavar="PATH",
                    help=f"the Chrome or Chromium binary (default: ${CHROME_ENV}, then PATH, then the usual app paths)")
    ap.add_argument("--cookie", action="append", default=[], metavar="NAME=VALUE", help="send a cookie; repeatable")
    ap.add_argument("--header", action="append", default=[], metavar="'NAME: VALUE'",
                    help="send a request header; repeatable")
    ap.add_argument("--probe-json", action="append", default=[], metavar="FILE",
                    help="judge a recorded probe instead of rendering; one file per viewport, repeatable")
    ap.add_argument("--dump-probe", metavar="DIR", help="also write each viewport's raw probe JSON into DIR")
    ap.add_argument("--all", action="store_true", help="print passing and skipped rows too, not only findings")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    ap.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    return ap


def page_url(page: str) -> str:
    if re.match(r"^[a-z][a-z0-9+.-]*://", page, re.I):
        if not re.match(r"^(https?|file)://", page, re.I):
            raise UsageError(f"not a web URL: {page}")
        if page.lower().startswith("file://") and not os.path.isfile(urllib.parse.unquote(urllib.parse.urlparse(page).path)):
            raise UsageError(f"no such file: {page}")
        return page
    if not os.path.isfile(page):
        raise UsageError(f"no such file: {page}")
    return Path(page).resolve().as_uri()


def render(args: argparse.Namespace) -> List[Dict[str, Any]]:
    url = page_url(args.page)
    exe = find_chrome(args.chrome)
    if not exe:
        given = args.chrome or os.environ.get(CHROME_ENV)
        if given:
            raise UsageError(f"Chrome not found at {given}")
        raise UsageError(f"no Chrome or Chromium found; pass --chrome PATH or set {CHROME_ENV}")
    headers = {}
    for h in args.header:
        k, sep, v = h.partition(":")
        if not sep or not k.strip():
            raise UsageError(f"header must be 'NAME: VALUE', got {h!r}")
        headers[k.strip()] = v.strip()
    probe_src = PROBE_FILE.read_text(encoding="utf-8")
    ch = Chrome(exe)
    try:
        return [measure(ch, url, w, h, probe_src, args.cookie, headers or None)
                for w, h in (args.viewport or DEFAULT_VIEWPORTS)]
    finally:
        ch.close()


def load_probes(paths: Sequence[str]) -> List[Dict[str, Any]]:
    probes = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError) as e:
            raise UsageError(f"unreadable probe {p}: {e}") from None
        try:
            check_probe(d)
        except ValueError as e:
            raise UsageError(f"malformed probe {p}: {e}") from None
        probes.append(d)
    return probes


def judge(probes: List[Dict[str, Any]], scale: Scale, screen: bool,
          asked: Optional[List[Tuple[int, int]]]) -> Dict[str, Any]:
    """Judge every viewport and put the result in one plain dict, the shape
    --json prints and the text report is drawn from."""
    viewports, allow_sets, findings = [], [], 0
    for n, d in enumerate(probes):
        rows, allows, sets, skipped = judge_viewport(d, scale, screen)
        laid = f"{d['viewport']['w']}x{d['viewport']['h']}"
        name = f"{asked[n][0]}x{asked[n][1]}" if asked else laid
        notes = []
        if asked and d["viewport"]["w"] != asked[n][0]:
            notes.append(f"laid out {d['viewport']['w']}px wide (the page has no viewport meta tag)")
        wait = d.get("settle") or {}
        if wait.get("loading"):
            notes.append(f"{wait['loading']} image(s) still loading after {IMAGES_WAIT_MS // 1000} s; measured anyway")
        if wait.get("gaveUp"):
            notes.append(f"still animating after {SETTLE_CAP_MS // 1000} s "
                         f"({wait.get('running', 0)} animation(s)); measured anyway")
        findings += sum(r["verdict"] == "FAIL" for r in rows)
        allow_sets.append(allows)
        viewports.append({"viewport": name, "sets": sets, "rows_skipped": skipped, "notes": notes, "rows": rows})
    # A declaration is one allow however many viewports see it: the viewport
    # that saw the most stands for the run.
    allows: List[Allow] = max(allow_sets, key=len) if allow_sets else []
    return {"verdict": "FAIL" if findings else "PASS", "findings": findings,
            "allows": [{"where": w, "declared": a} for w, a in allows], "viewports": viewports}


def text_report(result: Dict[str, Any], show_all: bool) -> str:
    """One line per finding, viewport first and the set's path last, so the
    measured numbers sit near the start of the line where a reader looks."""
    lines = []
    for vp in result["viewports"]:
        lines += [f"note {vp['viewport']}: {n}" for n in vp["notes"]]
        for r in vp["rows"]:
            if show_all or r["verdict"] in ("FAIL", "ALLOW"):
                lines.append(f"{r['verdict']} {vp['viewport']} {r['rule']}  {r['measurement']}  [{r['set']}]")
    lines += [f"allowed: {a['where']} ({a['declared']})" for a in result["allows"]]
    n, v = result["findings"], len(result["viewports"])
    sets = sum(vp["sets"] for vp in result["viewports"])
    lines.append(f"{result['verdict']}  {n} finding{'' if n == 1 else 's'}, {sets} set{'' if sets == 1 else 's'} "
                 f"judged across {v} viewport{'' if v == 1 else 's'}")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    if args.probe_json and args.page:
        raise UsageError("give a page or --probe-json, not both")
    if args.probe_json:
        probes = load_probes(args.probe_json)
        asked = None
        page = ", ".join(args.probe_json)
    elif args.page:
        probes = render(args)
        asked = args.viewport or DEFAULT_VIEWPORTS
        page = args.page
    else:
        raise UsageError("give an HTML file or URL to measure, or --probe-json FILE")
    scale: Scale = args.scale if args.scale else args.grid
    try:
        result = judge(probes, scale, args.screen, asked)
    except ValueError as e:
        raise UsageError(str(e)) from None
    except Exception as e:
        # A recorded probe is input: a shape check_probe let through is still
        # bad input, so it is one line and exit 2. On a rendered page the probe
        # is ours, and a failure there is a bug whose traceback should show.
        # SIGTERM and Ctrl-C are not Exceptions and still unwind past this.
        if not args.probe_json:
            raise
        raise UsageError(f"could not judge probe {page}: {type(e).__name__}: {e}") from None
    if args.dump_probe:
        stem = Path(urllib.parse.urlparse(page).path).stem or "page"
        os.makedirs(args.dump_probe, exist_ok=True)
        for d, vp in zip(probes, result["viewports"]):
            raw = {k: v for k, v in d.items() if k != "settle"}  # timings differ run to run
            with open(os.path.join(args.dump_probe, f"{stem}-{vp['viewport']}.json"), "w", encoding="utf-8") as f:
                json.dump(raw, f, indent=1)
                f.write("\n")
    if args.json:
        print(json.dumps({"page": page, **result}, indent=2))
    else:
        print(text_report(result, args.all))
    return 1 if result["findings"] else 0


def stop(signum: int, frame: Any) -> None:
    """SIGTERM unwinds like an exit, so Chrome and its profile are cleaned up."""
    raise SystemExit(128 + signum)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    before = signal.signal(signal.SIGTERM, stop)
    try:
        return run(args)
    except KeyboardInterrupt:
        print(f"{PROG}: interrupted", file=sys.stderr)
        return 130
    except (UsageError, MeasureError) as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"{PROG}: {e.strerror or e}: {e.filename or ''}".rstrip(": "), file=sys.stderr)
        return 2
    finally:
        signal.signal(signal.SIGTERM, before)
