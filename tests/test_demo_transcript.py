"""demo/transcript.json is the session the README picture shows, so it must
be what the commands really print.

The replay runs every recorded command with bash in a throwaway copy of the
checkout and compares output and exit code exactly; it needs Chrome and
skips without it. The picture check needs nothing: every row drawn in
demo/terminal.svg must trace back to the transcript, in order.

Regenerate after a change to the output: UPDATE_DEMO_TRANSCRIPT=1 python -m
unittest discover -s tests -p test_demo_transcript.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple

from layout_ruler.chrome import find_chrome

ROOT = Path(__file__).parent.parent
TRANSCRIPT = ROOT / "demo" / "transcript.json"
PICTURE = ROOT / "demo" / "terminal.svg"
PLACEHOLDER = "/path/to/checkout"
NS = {"svg": "http://www.w3.org/2000/svg"}
ELLIPSIS = "…"
SKIPPED = shutil.ignore_patterns(".git", "__pycache__", "*.egg-info", "build", "dist", ".venv")


def replay(entries: List[dict]) -> List[dict]:
    """Run each command in order in one fresh copy, stderr folded into stdout."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "layout-ruler"
        shutil.copytree(ROOT, copy, ignore=SKIPPED)
        out = []
        for e in entries:
            p = subprocess.run(["bash", "-c", e["cmd"]], cwd=str(copy), text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
            text = p.stdout
            for form in (str(copy.resolve()), str(copy)):  # macOS resolves /var to /private/var
                text = text.replace(form, PLACEHOLDER)
            out.append({"cmd": e["cmd"], "out": text.rstrip("\n"), "status": p.returncode})
        return out


@unittest.skipUnless(find_chrome(), "no Chrome or Chromium found; the demo commands render pages")
class TestReplay(unittest.TestCase):
    def test_every_command_prints_what_was_recorded(self) -> None:
        recorded = json.loads(TRANSCRIPT.read_text(encoding="utf-8"))
        fresh = replay(recorded)
        if os.environ.get("UPDATE_DEMO_TRANSCRIPT"):
            TRANSCRIPT.write_text(json.dumps(fresh, indent=2) + "\n", encoding="utf-8")
            recorded = fresh
        for want, got in zip(recorded, fresh):
            with self.subTest(cmd=want["cmd"]):
                self.assertEqual(got["out"], want["out"])
                self.assertEqual(got["status"], want["status"])


class TestPicture(unittest.TestCase):
    def test_each_drawn_row_traces_back_to_the_transcript_in_order(self) -> None:
        drawn = picture_rows()
        self.assertTrue(drawn, "the picture draws no session rows")
        at = 0
        for entry in json.loads(TRANSCRIPT.read_text(encoding="utf-8")):
            if at == len(drawn):
                break  # the picture may end between whole commands
            kind, text = drawn[at]
            self.assertEqual(kind, "cmd", f"row {at + 1} should start the command {entry['cmd']!r}")
            parts = [text]
            at += 1
            while at < len(drawn) and drawn[at][0] == "more":
                parts.append(drawn[at][1])
                at += 1
            self.assertEqual(unwrap(parts), entry["cmd"])
            for line in [l for l in entry["out"].splitlines() if l.strip()]:
                self.assertLess(at, len(drawn), f"the picture stops inside {entry['cmd']!r}")
                kind, text = drawn[at]
                self.assertEqual(kind, "out", f"row {at + 1} should be the output line {line!r}")
                self.assertTrue(cut_from(text, line), f"row {at + 1} {text!r} is not {line!r} or its start")
                at += 1
        self.assertEqual(at, len(drawn), "the picture draws rows the transcript does not hold")


def unwrap(parts: List[str]) -> str:
    """A long command is drawn over several rows, each but the last ending in
    ' \\'; the break took one space."""
    return " ".join(p[:-2] if p.endswith(" \\") else p for p in parts)


def cut_from(text: str, line: str) -> bool:
    """The drawn row is the whole line, or its start with one trailing ellipsis."""
    if text == line:
        return True
    return text.endswith(ELLIPSIS) and text.count(ELLIPSIS) == 1 and line.startswith(text[:-1]) and len(text) - 1 < len(line)


def picture_rows() -> List[Tuple[str, str]]:
    """(kind, text) per drawn row: 'cmd' for a prompt row, 'more' for a
    command's continuation (indented four spaces), 'out' for output. The
    title bar is the one text element with its own font size."""
    rows = []
    for el in ET.parse(PICTURE).getroot().findall("svg:text", NS):
        if el.get("font-size"):
            continue
        spans = el.findall("svg:tspan", NS)
        if spans:
            rows.append(("cmd", spans[-1].text or ""))
        elif el.get("class") == "cmd":
            rows.append(("more", (el.text or "")[4:]))
        else:
            rows.append(("out", el.text or ""))
    return rows


if __name__ == "__main__":
    unittest.main()
