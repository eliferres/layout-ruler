"""End to end in a real browser: render the demo pages and check what the
command reports at both default widths. Skipped, with the reason, when no
Chrome or Chromium binary is found (see find_chrome for the lookup order)."""
from __future__ import annotations

import http.server
import json
import os
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zlib
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
        self.assertIn("spread 4.00px; row 3 span.amount +4px from span.name", p.stdout)

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

    def test_a_page_that_calls_alert_is_measured(self) -> None:
        """JavaScript dialogs are dismissed as they open; otherwise the page
        never fires its load event."""
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "alert.html"
            page.write_text("<!doctype html><script>alert('hello'); confirm('sure?')</script><p>Text</p>", encoding="utf-8")
            p = ruler(str(page), "--viewport", "1280x900")
        self.assertEqual((p.returncode, p.stderr), (0, ""))

    def test_stopping_a_run_leaves_no_profile_and_no_traceback(self) -> None:
        for sig, code, said in ((signal.SIGINT, 130, "layout-ruler: interrupted\n"), (signal.SIGTERM, 143, "")):
            with self.subTest(signal=sig.name), tempfile.TemporaryDirectory() as tmp:
                env = dict(os.environ, TMPDIR=tmp)
                proc = subprocess.Popen([sys.executable, "-m", "layout_ruler", "demo/aligned.html"], cwd=str(ROOT),
                                        env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                deadline = time.time() + 20
                while not any(Path(tmp).glob("layout-ruler-*")) and time.time() < deadline:
                    time.sleep(0.05)
                time.sleep(1)  # well into the page load
                proc.send_signal(sig)
                out, err = proc.communicate(timeout=30)
                self.assertEqual((proc.returncode, err), (code, said))
                self.assertEqual(list(Path(tmp).glob("layout-ruler-*")), [])

    def test_a_file_url_and_a_path_measure_the_same(self) -> None:
        url = (ROOT / "demo" / "aligned.html").as_uri()
        a = json.loads(ruler(url, "--json", "--viewport", "1280x900").stdout)
        b = json.loads(ruler("demo/aligned.html", "--json", "--viewport", "1280x900").stdout)
        self.assertEqual(a["viewports"], b["viewports"])


def png(width: int, height: int) -> bytes:
    """A blank greyscale PNG, built by hand so the test needs no image file."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"".join(b"\0" + b"\xff" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# Content arrives only after the page is scrolled to its first bottom edge:
# a script then adds 3000px more page and, at its end, a lazy image the server
# sends two seconds late. Once loaded the image is 1600px wide and runs off
# the screen, so a sweep that stops at the first page height, or does not wait
# for the image, reports a clean page.
LATE_PAGE = b"""<!doctype html><meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{margin:0} .tall{height:2000px} .more{height:3000px}</style>
<div class="tall"></div>
<script>
let added = false;
addEventListener('scroll', () => {
  if (added || scrollY + innerHeight < document.documentElement.scrollHeight - 10) return;
  added = true;
  document.body.insertAdjacentHTML('beforeend', '<div class="more"></div><img loading="lazy" src="/wide.png">');
});
</script>"""


class LateServer(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/wide.png":
            time.sleep(2)
            body, kind = png(1600, 8), "image/png"
        else:
            body, kind = LATE_PAGE, "text/html"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@unittest.skipUnless(CHROME, "no Chrome or Chromium found; pass --chrome or set LAYOUT_RULER_CHROME to run the live tests")
class TestLazyContent(unittest.TestCase):
    def test_content_added_while_sweeping_and_slow_images_are_measured(self) -> None:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), LateServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            p = ruler(f"http://127.0.0.1:{server.server_address[1]}/", "--viewport", "1280x900")
        finally:
            server.shutdown()
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("scrollWidth 1600 vs 1280", p.stdout)


if __name__ == "__main__":
    unittest.main()
