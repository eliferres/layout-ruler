"""End to end in a real browser: render the demo pages and check what the
command reports at both default widths. Skipped, with the reason, when no
Chrome or Chromium binary is found (see find_chrome for the lookup order)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from layout_ruler.chrome import find_chrome

ROOT = Path(__file__).parent.parent
CHROME = find_chrome()

# page -> (exit code, {viewport: the rules that fail there})
EXPECTED = {
    "aligned": (0, {"1280x900": [], "375x812": []}),
    "ragged-dots": (1, {"1280x900": ["columns"], "375x812": ["columns"]}),
    "uneven-gaps": (1, {"1280x900": ["gap-scale", "gaps"], "375x812": ["gap-scale", "gaps"]}),
    "unequal-heights": (1, {"1280x900": ["equal-size"], "375x812": ["equal-size"]}),
    "baseline-off": (1, {"1280x900": ["baselines"], "375x812": ["baselines"]}),
    "overflow": (1, {"1280x900": [], "375x812": ["viewport"]}),
}


def ruler(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "layout_ruler", *args], cwd=str(ROOT), text=True,
                          capture_output=True, timeout=180)


@unittest.skipUnless(CHROME, "no Chrome or Chromium found; pass --chrome or set LAYOUT_RULER_CHROME to run the live tests")
class TestLive(unittest.TestCase):
    def test_each_demo_page_fails_on_exactly_its_planted_fault(self) -> None:
        for page, (code, want) in EXPECTED.items():
            with self.subTest(page=page):
                p = ruler(f"demo/{page}.html", "--json")
                self.assertEqual(p.returncode, code, p.stderr)
                got = {vp["viewport"]: sorted({r["rule"] for r in vp["rows"] if r["verdict"] == "FAIL"})
                       for vp in json.loads(p.stdout)["viewports"]}
                self.assertEqual(got, want)

    def test_the_planted_numbers_are_measured_exactly(self) -> None:
        """The demo pages set every size in whole CSS pixels, so these hold
        on any platform font."""
        p = ruler("demo/ragged-dots.html", "--viewport", "1280x900")
        self.assertIn("left edges 96,152,112,176,104", p.stdout)
        p = ruler("demo/baseline-off.html", "--viewport", "375x812")
        self.assertIn("row 3 span.name 0, span.status 0, span.amount +4px", p.stdout)

    def test_a_page_whose_stylesheet_is_missing_is_an_error_not_a_measurement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "unstyled.html"
            page.write_text('<!doctype html><link rel="stylesheet" href="missing.css"><h1>Hi</h1>', encoding="utf-8")
            p = ruler(str(page), "--viewport", "1280x900")
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, "")
        self.assertIn("stylesheet not loaded after one reload with the cache off", p.stderr)
        self.assertIn("missing.css", p.stderr)
        self.assertEqual(len(p.stderr.strip().splitlines()), 1)

    def test_a_file_url_and_a_path_measure_the_same(self) -> None:
        url = (ROOT / "demo" / "aligned.html").as_uri()
        a = json.loads(ruler(url, "--json", "--viewport", "1280x900").stdout)
        b = json.loads(ruler("demo/aligned.html", "--json", "--viewport", "1280x900").stdout)
        self.assertEqual(a["viewports"], b["viewports"])


if __name__ == "__main__":
    unittest.main()
