"""The command line: output, exit codes and one-line errors. Every case here
judges recorded probes or fails before a browser starts, so none needs Chrome."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from layout_ruler import __version__, cli
from layout_ruler.chrome import find_chrome

ROOT = Path(__file__).parent.parent
FIX = "tests/fixtures"


def ruler(*args: str, env: object = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "layout_ruler", *args], cwd=str(ROOT), text=True,
                          capture_output=True, env=env)


class TestOutput(unittest.TestCase):
    def test_version(self) -> None:
        p = ruler("--version")
        self.assertEqual((p.returncode, p.stdout.strip()), (0, f"layout-ruler {__version__}"))

    def test_a_clean_page_exits_0_and_prints_only_its_summary(self) -> None:
        p = ruler("--probe-json", f"{FIX}/aligned-list.json")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout, "PASS  0 findings, 1 set judged across 1 viewport\n")

    def test_a_finding_exits_1_and_prints_its_measurement(self) -> None:
        p = ruler("--probe-json", f"{FIX}/unequal-heights.json")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout.splitlines(), [
            "FAIL 1280x900 equal-size  heights 48,48,72,48,48px; row 3 off 48px  [body > ul.list]",
            "FAIL  1 finding, 1 set judged across 1 viewport",
        ])

    def test_all_prints_passing_and_skipped_rows(self) -> None:
        p = ruler("--probe-json", f"{FIX}/nav-widths.json", "--all")
        self.assertIn("PASS 1280x900 gaps  gaps 24,23.99,24,24px  [body > nav.nav]", p.stdout)
        self.assertIn("SKIP 1280x900 equal-size  widths ", p.stdout)

    def test_allows_are_listed(self) -> None:
        p = ruler("--probe-json", f"{FIX}/off-twice.json")
        self.assertEqual(p.returncode, 0)
        self.assertIn('allowed: subtree 2 of 2 (data-ruler="off")', p.stdout)

    def test_several_probes_are_one_run(self) -> None:
        p = ruler("--probe-json", f"{FIX}/one-px-bar.json", "--probe-json", f"{FIX}/one-px-bar-375.json")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout.splitlines(), [
            "FAIL 375x812 viewport  scrollWidth 376 vs 375; 0 box(es) outside; widest box ends at 376  [page]",
            "FAIL  1 finding, 0 sets judged across 2 viewports",
        ])

    def test_json_carries_every_row(self) -> None:
        p = ruler("--probe-json", f"{FIX}/uneven-gaps.json", "--json")
        d = json.loads(p.stdout)
        self.assertEqual((p.returncode, d["verdict"], d["findings"]), (1, "FAIL", 2))
        rules = [r["rule"] for r in d["viewports"][0]["rows"]]
        self.assertIn("columns", rules)
        self.assertEqual(set(d), {"page", "verdict", "findings", "allows", "viewports"})

    def test_grid_and_scale_set_the_spacing_scale(self) -> None:
        self.assertEqual(ruler("--probe-json", f"{FIX}/uneven-gaps.json", "--grid", "6").stdout.count("FAIL 1280x900"), 1)
        p = ruler("--probe-json", f"{FIX}/uneven-gaps.json", "--scale", "12,18")
        self.assertNotIn("gap-scale", p.stdout)
        self.assertIn("FAIL 1280x900 gaps  gaps 12,12,18,12px", p.stdout)

    def test_dump_probe_writes_what_was_judged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ruler("--probe-json", f"{FIX}/aligned-list.json", "--dump-probe", tmp)
            dumped = list(Path(tmp).iterdir())
            self.assertEqual(len(dumped), 1)
            self.assertEqual(json.loads(dumped[0].read_text()), json.loads((ROOT / FIX / "aligned-list.json").read_text()))


class TestErrors(unittest.TestCase):
    def assert_error(self, p: subprocess.CompletedProcess, text: str) -> None:
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, "")
        self.assertEqual(p.stderr.strip().splitlines()[-1], text)
        self.assertNotIn("Traceback", p.stderr)

    def test_a_missing_page(self) -> None:
        self.assert_error(ruler("demo/nope.html"), "layout-ruler: no such file: demo/nope.html")

    def test_a_url_that_is_not_web(self) -> None:
        self.assert_error(ruler("ftp://example.test/page"), "layout-ruler: not a web URL: ftp://example.test/page")

    def test_nothing_to_measure(self) -> None:
        self.assert_error(ruler(), "layout-ruler: give an HTML file or URL to measure, or --probe-json FILE")

    def test_a_page_and_a_probe_together(self) -> None:
        self.assert_error(ruler(f"{FIX}/aligned-list.html", "--probe-json", f"{FIX}/aligned-list.json"),
                          "layout-ruler: give a page or --probe-json, not both")

    def test_an_unreadable_probe(self) -> None:
        p = ruler("--probe-json", "README.md")
        self.assertEqual(p.returncode, 2)
        self.assertTrue(p.stderr.startswith("layout-ruler: unreadable probe README.md: "))
        self.assertEqual(len(p.stderr.strip().splitlines()), 1)

    def test_a_malformed_probe_is_one_line_naming_the_bad_field(self) -> None:
        good = json.loads((ROOT / FIX / "aligned-list.json").read_text())

        def broken(edit: object) -> object:
            d = json.loads(json.dumps(good))
            edit(d)
            return d

        cases = {
            "top level": ([], "the probe is not an object"),
            "null": (None, "the probe is not an object"),
            "no viewport": ({"sets": []}, "viewport is missing"),
            "empty set": (broken(lambda d: d["sets"][0].update(rows=[])), "sets[0].rows is empty"),
            "string cell": (broken(lambda d: d["sets"][0]["rows"][0]["cells"].__setitem__(0, "x")),
                            "sets[0].rows[0].cells[0] is not an object"),
            "string coordinate": (broken(lambda d: d["sets"][0]["rows"][0]["box"].update(x="a")),
                                  "sets[0].rows[0].box.x is not a number"),
            "null set": (broken(lambda d: d.update(sets=[None])), "sets[0] is not an object"),
            "string overflow": (broken(lambda d: d.update(overflow=["x"])), "overflow[0] is not an object"),
        }
        for name, (probe, why) in cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "probe.json"
                path.write_text(json.dumps(probe))
                self.assert_error(ruler("--probe-json", str(path)), f"layout-ruler: malformed probe {path}: {why}")

    def test_a_chrome_path_that_does_not_exist(self) -> None:
        self.assert_error(ruler(f"{FIX}/aligned-list.html", "--chrome", "/nonexistent/chrome"),
                          "layout-ruler: Chrome not found at /nonexistent/chrome")

    def test_no_chrome_anywhere(self) -> None:
        err = io.StringIO()
        with mock.patch.object(cli, "find_chrome", return_value=None), mock.patch.dict(os.environ, {"LAYOUT_RULER_CHROME": ""}), \
                contextlib.redirect_stderr(err):
            code = cli.main([str(ROOT / FIX / "aligned-list.html")])
        self.assertEqual((code, err.getvalue()),
                         (2, "layout-ruler: no Chrome or Chromium found; pass --chrome PATH or set LAYOUT_RULER_CHROME\n"))

    def test_bad_arguments_exit_2(self) -> None:
        for args in (["--viewport", "wide"], ["--grid", "0"], ["--scale", "a,b"]):
            with self.subTest(args=args):
                p = ruler(*args, "--probe-json", f"{FIX}/aligned-list.json")
                self.assertEqual(p.returncode, 2)
                self.assertTrue(p.stderr.startswith("usage: layout-ruler"))


class TestFindChrome(unittest.TestCase):
    """--chrome first, then $LAYOUT_RULER_CHROME, then PATH, then app paths."""

    def test_an_explicit_path_wins_and_is_never_replaced_by_a_guess(self) -> None:
        with mock.patch.dict(os.environ, {"LAYOUT_RULER_CHROME": sys.executable}):
            self.assertEqual(find_chrome(sys.executable), sys.executable)
            self.assertIsNone(find_chrome("/nonexistent/chrome"))
            self.assertEqual(find_chrome(), sys.executable)

    def test_path_names_come_before_app_paths(self) -> None:
        with mock.patch.dict(os.environ, {"LAYOUT_RULER_CHROME": ""}), \
                mock.patch("shutil.which", side_effect=lambda n: "/usr/bin/" + n if n == "chromium" else None):
            self.assertEqual(find_chrome(), "/usr/bin/chromium")

    def test_nothing_found(self) -> None:
        with mock.patch.dict(os.environ, {"LAYOUT_RULER_CHROME": ""}), mock.patch("shutil.which", return_value=None), \
                mock.patch("layout_ruler.chrome.CHROME_APPS", ()):
            self.assertIsNone(find_chrome())


if __name__ == "__main__":
    unittest.main()
