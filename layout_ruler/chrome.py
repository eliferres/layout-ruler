"""Drive headless Chrome over the DevTools protocol and run the probe in a page.

The transport is --remote-debugging-pipe: Chrome reads protocol messages on
file descriptor 3 and writes on 4, each a JSON object ended by a NUL byte. A
pipe needs no free port, no HTTP handshake and no WebSocket client, so the
whole driver is the standard library (os.pipe, subprocess, json, threading),
and nothing else on the machine can attach to the browser while it runs.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

PHONE_MAX = 480  # at or under this width the page is emulated as a phone (touch, viewport meta honoured)
PHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
CHROME_ENV = "LAYOUT_RULER_CHROME"
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
CHROME_APPS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
)


class MeasureError(Exception):
    """The page could not be measured. The command reports it and exits 2."""


def find_chrome(explicit: Optional[str] = None) -> Optional[str]:
    """The browser binary: --chrome, then $LAYOUT_RULER_CHROME, then the
    common names on PATH, then the usual macOS application paths."""
    for given in (explicit, os.environ.get(CHROME_ENV)):
        if given:
            return given if os.path.isfile(given) and os.access(given, os.X_OK) else None
    for name in CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return next((p for p in CHROME_APPS if os.path.isfile(p)), None)


class Chrome:
    """One headless Chrome, spoken to over the debugging pipe."""

    def __init__(self, exe: str) -> None:
        self.profile = tempfile.mkdtemp(prefix="layout-ruler-")
        r_in, w_in = os.pipe()    # we write, Chrome reads (fd 3)
        r_out, w_out = os.pipe()  # Chrome writes, we read (fd 4)
        args = [exe, "--headless=new", "--remote-debugging-pipe", "--no-first-run", "--no-default-browser-check",
                "--disable-gpu", "--hide-scrollbars", "--disable-extensions", "--disable-background-networking",
                "--window-size=1280,900", f"--user-data-dir={self.profile}", "--enable-unsafe-swiftshader",
                "--disable-features=TranslateUI", "--mute-audio", "about:blank"]

        # Runs in the child between fork and exec. os.pipe() descriptors are
        # close-on-exec, and dup2(fd, fd) is a no-op that never clears that
        # flag, so a pipe end that already sits on 3 would silently close at
        # exec. Move the write end off 3 first, then place both and mark them
        # inheritable. close_fds stays False because with it Python closes the
        # placed 3 and 4 again whenever the parent already held low descriptors.
        def wire() -> None:
            a, b = r_in, w_out
            if b == 3:
                b = os.dup(b)
            if a != 3:
                os.dup2(a, 3)
            os.set_inheritable(3, True)
            if b != 4:
                os.dup2(b, 4)
            os.set_inheritable(4, True)

        self.errlog = os.path.join(self.profile, "chrome-stderr.log")
        with open(self.errlog, "ab") as err:
            self.p = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err,
                                      close_fds=False, preexec_fn=wire)
        os.close(r_in)
        os.close(w_out)
        self.w = os.fdopen(w_in, "wb", buffering=0)
        self.r = os.fdopen(r_out, "rb", buffering=0)
        self.id = 0
        self.pending: Dict[int, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []
        self.lock = threading.Lock()
        self.cv = threading.Condition(self.lock)
        self.dead = False
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        buf = b""
        while True:
            try:
                chunk = self.r.read(65536)
            except OSError:
                chunk = b""
            if not chunk:
                with self.cv:
                    self.dead = True
                    self.cv.notify_all()
                return
            buf += chunk
            while b"\0" in buf:
                msg, buf = buf.split(b"\0", 1)
                try:
                    m = json.loads(msg)
                except ValueError:
                    continue
                with self.cv:
                    if "id" in m:
                        self.pending[m["id"]] = m
                    else:
                        self.events.append(m)
                    self.cv.notify_all()

    def send(self, method: str, params: Optional[Dict[str, Any]] = None, session: Optional[str] = None,
             timeout: float = 45) -> Dict[str, Any]:
        with self.lock:
            self.id += 1
            mid = self.id
        m: Dict[str, Any] = {"id": mid, "method": method, "params": params or {}}
        if session:
            m["sessionId"] = session
        try:
            self.w.write(json.dumps(m).encode() + b"\0")
        except OSError:
            raise MeasureError("Chrome exited: " + self._stderr_tail()) from None
        end = time.time() + timeout
        with self.cv:
            while mid not in self.pending:
                if self.dead:
                    raise MeasureError("Chrome exited: " + self._stderr_tail())
                left = end - time.time()
                if left <= 0:
                    raise MeasureError(f"Chrome did not answer {method} in {timeout:g} s")
                self.cv.wait(left)
            r = self.pending.pop(mid)
        if "error" in r:
            raise MeasureError(f"{method}: {r['error'].get('message', r['error'])}")
        return r.get("result", {})

    def _stderr_tail(self, n: int = 300) -> str:
        try:
            with open(self.errlog, "rb") as f:
                tail = f.read()[-n:].decode(errors="replace").strip()
            return " ".join(tail.split()) or "(no stderr)"
        except OSError:
            return "(stderr unavailable)"

    def wait_event(self, name: str, session: str, timeout: float = 30) -> Optional[Dict[str, Any]]:
        end = time.time() + timeout
        with self.cv:
            while True:
                for i, e in enumerate(self.events):
                    if e.get("method") == name and e.get("sessionId") == session:
                        return self.events.pop(i)
                left = end - time.time()
                if left <= 0 or self.dead:
                    return None
                self.cv.wait(left)

    def new_page(self) -> str:
        t = self.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        s = self.send("Target.attachToTarget", {"targetId": t, "flatten": True})["sessionId"]
        for domain in ("Page", "Runtime", "Network"):
            self.send(f"{domain}.enable", session=s)
        return s

    def close_page(self, s: str) -> None:
        try:
            self.send("Page.close", session=s, timeout=10)
        except MeasureError:
            pass  # Chrome closes with the run anyway

    def close(self) -> None:
        try:
            self.send("Browser.close", timeout=5)
        except MeasureError:
            pass
        # Let Chrome finish its own exit before the kill: a kill mid-shutdown
        # leaves temporary files behind on macOS.
        try:
            self.p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.p.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


# Finite animations (CSS animations and transitions, Web Animations) end
# before a box is read: an entrance slide read halfway puts a row a few pixels
# off its column. The wait is never under one second (a script-driven tween is
# no Animation the page can list) and never over six in all; an infinite
# animation is never waited for. Resolves to {running, gaveUp, ms}.
SETTLE_MS, SETTLE_CAP_MS = 1000, 6000
SETTLE_JS = """new Promise((done) => {
  const start = performance.now(), since = () => performance.now() - start;
  const frames = (f) => requestAnimationFrame(() => requestAnimationFrame(f));
  const running = () => document.getAnimations().filter((a) => a.playState === 'running' && a.effect
    && Number.isFinite(a.effect.getComputedTiming().endTime));
  const finish = (gaveUp) => frames(() => done({ running: gaveUp ? running().length : 0, gaveUp, ms: Math.round(since()) }));
  const check = () => {
    const busy = running(), left = %d - since();
    if (left <= 0) return finish(true);
    if (busy.length) {
      return Promise.race([Promise.all(busy.map((a) => a.finished.catch(() => null))), new Promise((r) => setTimeout(r, left))])
        .then(() => frames(check));
    }
    if (since() >= %d) return finish(false);
    setTimeout(() => frames(check), %d - since());  // an animation a script starts late is still waited for
  };
  frames(check);
})""" % (SETTLE_CAP_MS, SETTLE_MS, SETTLE_MS)

# Lazy content: scroll down in 700px steps, re-reading the page height at
# every step so content a script adds near the bottom is scrolled through
# too, down to SWEEP_CAP_PX. Then back to the top, and wait (up to
# IMAGES_WAIT_MS) for every image still loading, which includes each lazy
# image the scroll set off. Resolves to {loading}: images still unfinished
# when the wait gave up.
SWEEP_CAP_PX, IMAGES_WAIT_MS = 12000, 5000
SWEEP_JS = """new Promise((done) => {
  let y = 0;
  const step = () => {
    y += 700;
    scrollTo(0, y);
    if (y < document.documentElement.scrollHeight && y < %d) return setTimeout(step, 50);
    scrollTo(0, 0);
    const pending = [...document.images].filter((i) => !i.complete);
    const loaded = pending.map((i) => new Promise((r) => {
      i.addEventListener('load', r, { once: true });
      i.addEventListener('error', r, { once: true });
    }));
    Promise.race([Promise.all(loaded), new Promise((r) => setTimeout(r, %d))])
      .then(() => setTimeout(() => done({ loading: [...document.images].filter((i) => !i.complete).length }), 300));
  };
  step();
})""" % (SWEEP_CAP_PX, IMAGES_WAIT_MS)

# A page read before its stylesheets arrive is measured as browser defaults
# (body margin 8px, h1 32px), numbers from a render nobody ships. So every
# linked stylesheet that applies at this width must have arrived before the
# read: rel stylesheet, not disabled, not an alternate, no type other than
# text/css, and a media that matches unless the link has an onload (the async
# pattern media=print onload=all, whose failed sheet leaves the page
# unstyled). Chrome gives a failed sheet an empty sheet, not a null one, so
# two signals are read: a sheet still null after the wait is pending, and a
# linked URL none of whose requests succeeded while one failed is failed. A
# request fails on a network error, an HTTP status of 400 or more, or (outside
# quirks mode) a Content-Type other than text/css, such as a CDN's HTML error
# page sent with a 200. The preload swap (rel=preload as=style whose onload
# makes it a stylesheet) is read on the network only: waited for while its
# request is on the wire, named if it failed. A page missing a sheet is loaded
# once more with the cache off; still missing, the run is an error.
STYLES_WAIT_MS = 10000
STYLES_JS = """new Promise((done) => {
  const start = performance.now();
  const onload = (l) => l.hasAttribute('onload') || !!l.onload;
  const links = () => [...document.querySelectorAll('link[rel~="stylesheet" i]')]
    .filter((l) => !l.disabled && !/(^|\\s)alternate(\\s|$)/i.test(l.rel) && (l.getAttribute('href') || '').trim()
      && (!l.type.trim() || /^text\\/css\\s*(;|$)/i.test(l.type.trim()))
      && (matchMedia(l.media || 'all').matches || onload(l)));
  const swaps = () => [...document.querySelectorAll('link[rel~="preload" i][as="style" i]')]
    .filter((l) => onload(l) && (l.getAttribute('href') || '').trim()).map((l) => l.href);
  const look = () => {
    const all = links(), pending = all.filter((l) => !l.sheet).map((l) => l.href);
    if (!pending.length || performance.now() - start >= %d)
      return done({ linked: all.map((l) => l.href), pending, swaps: swaps(), quirks: document.compatMode === 'BackCompat' });
    setTimeout(look, 100);
  };
  look();
})""" % STYLES_WAIT_MS

Net = Tuple[Dict[str, Set[str]], Dict[str, str], Set[str], Set[str]]


class StylesMissing(Exception):
    pass


def sheet_requests(events: Iterable[Dict[str, Any]], session: str, quirks: bool = False) -> Net:
    """This page's requests from the protocol events: the URLs each passed
    through (a redirect keeps its requestId), the failed ones with why, the
    ones that finished, and the ones that ended either way."""
    urls: Dict[str, Set[str]] = {}
    bad: Dict[str, str] = {}
    good: Set[str] = set()
    ended: Set[str] = set()
    for e in events:
        if e.get("sessionId") != session:
            continue
        m, p = e.get("method"), e.get("params") or {}
        rid = p.get("requestId")
        if m == "Network.requestWillBeSent":
            urls.setdefault(rid, set()).add((p.get("request") or {}).get("url"))
        elif m == "Network.responseReceived":
            r = p.get("response") or {}
            # The type the server sent. With no Content-Type header Chrome
            # applies the sheet, while the protocol's mimeType reports its own
            # guess, so the guess is never judged.
            sent = next((str(v) for k, v in (r.get("headers") or {}).items() if k.lower() == "content-type"), "")
            mime = sent.split(";", 1)[0].strip().lower()
            if (r.get("status") or 0) >= 400:
                bad[rid] = f"HTTP {r['status']}"
            elif mime and mime != "text/css" and not quirks:
                bad[rid] = f"served as {mime}, not text/css"
        elif m == "Network.loadingFailed":
            ended.add(rid)
            if not p.get("canceled"):
                bad[rid] = (p.get("errorText") or "failed") + (f", {p['blockedReason']}" if p.get("blockedReason") else "")
        elif m == "Network.loadingFinished":
            good.add(rid)
            ended.add(rid)
    return urls, bad, good, ended


def request_ids(urls: Dict[str, Set[str]], href: str) -> List[str]:
    bare = href.split("#", 1)[0]  # the network never sees a #fragment
    return [r for r, u in urls.items() if bare in u]


def swaps_on_wire(swaps: Sequence[str], linked: Sequence[str], net: Net) -> List[str]:
    """Preload swaps (not also linked) Chrome is still fetching: a request
    sent, not all ended, none loaded. One never fetched is never waited for."""
    urls, bad, good, ended = net
    out = []
    for href in dict.fromkeys(swaps):
        rids = request_ids(urls, href)
        if href not in linked and rids and not all(r in ended for r in rids) \
                and not any(r in good and r not in bad for r in rids):
            out.append(href)
    return out


def missing_sheets(linked: Sequence[str], pending: Sequence[str], events: Iterable[Dict[str, Any]], session: str,
                   quirks: bool = False, swaps: Sequence[str] = ()) -> List[str]:
    """Every linked sheet the page does not have, as `<href> (<why>)`, in link
    order, then each preload swap that failed or is still on the wire. Pure
    over the page's lists and the protocol events, so it is tested without Chrome."""
    net = sheet_requests(events, session, quirks)
    urls, bad, good, _ = net
    slow = swaps_on_wire(swaps, linked, net)
    out = []
    for href in dict.fromkeys([*linked, *swaps]):
        rids = request_ids(urls, href)
        failed = [bad[r] for r in rids if r in bad]
        if href in pending or href in slow:
            out.append(f"{href} ({failed[0] if failed else f'not loaded in {STYLES_WAIT_MS // 1000} s'})")
        elif failed and not any(r in good and r not in bad for r in rids):
            out.append(f"{href} ({failed[0]})")
    return out


def evaluate(ch: Chrome, s: str, expression: str, timeout: float = 30) -> Any:
    r = ch.send("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True},
                session=s, timeout=timeout)
    if r.get("exceptionDetails"):
        ex = r["exceptionDetails"]
        why = (ex.get("exception") or {}).get("description") or ex.get("text") or "an exception"
        raise MeasureError("script in the page threw: " + why.splitlines()[0][:200])
    return r["result"].get("value")


def check_styles(ch: Chrome, s: str) -> None:
    """Raise StylesMissing naming each linked sheet the page does not have."""
    def ask() -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        page = evaluate(ch, s, STYLES_JS, timeout=STYLES_WAIT_MS / 1000 + 15)
        with ch.cv:
            return page, list(ch.events)
    page, events = ask()
    start, waited = time.monotonic(), False
    while swaps_on_wire(page.get("swaps") or (), page["linked"], sheet_requests(events, s)) \
            and time.monotonic() - start < STYLES_WAIT_MS / 1000:
        time.sleep(0.1)
        waited = True
        with ch.cv:
            events = list(ch.events)
    if waited:  # a swap that loaded is a stylesheet link now, and its sheet is waited for like any other
        page, events = ask()
    reasons = missing_sheets(page["linked"], page["pending"], events, s, bool(page.get("quirks")), page.get("swaps") or ())
    if reasons:
        raise StylesMissing("; ".join(reasons))


def measure(ch: Chrome, url: str, width: int, height: int, probe_src: str,
            cookies: Sequence[str] = (), headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """One viewport, with one reload for a page missing a stylesheet."""
    try:
        return measure_once(ch, url, width, height, probe_src, cookies, headers)
    except StylesMissing:
        try:
            d = measure_once(ch, url, width, height, probe_src, cookies, headers, fresh=True)
        except StylesMissing as again:
            raise MeasureError(f"{url} at {width}x{height}: stylesheet not loaded after one reload "
                               f"with the cache off: {again}") from None
        return d


def measure_once(ch: Chrome, url: str, width: int, height: int, probe_src: str, cookies: Sequence[str] = (),
                 headers: Optional[Dict[str, str]] = None, fresh: bool = False) -> Dict[str, Any]:
    """Load the page at one viewport, let fonts and late content settle, wait
    for its animations, check its stylesheets, and run the probe."""
    s = ch.new_page()
    try:
        if fresh:  # a cached error response must not be replayed
            ch.send("Network.setCacheDisabled", {"cacheDisabled": True}, session=s)
        # The probe's baseline marker is an element with a style attribute; a
        # page whose policy blocks inline styles would silently drop it.
        ch.send("Page.setBypassCSP", {"enabled": True}, session=s)
        mobile = width <= PHONE_MAX
        ch.send("Emulation.setDeviceMetricsOverride",
                {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": mobile}, session=s)
        if mobile:
            ch.send("Emulation.setTouchEmulationEnabled", {"enabled": True}, session=s)
            ch.send("Network.setUserAgentOverride", {"userAgent": PHONE_UA}, session=s)
        if headers:
            ch.send("Network.setExtraHTTPHeaders", {"headers": headers}, session=s)
        host = urllib.parse.urlparse(url).hostname or "localhost"
        for c in cookies:
            name, _, value = c.partition("=")
            ch.send("Network.setCookie", {"name": name.strip(), "value": value.strip(), "domain": host, "path": "/"},
                    session=s)
        # A load event still queued from the blank page this tab opened on
        # would be taken for this page's: drop any before navigating.
        with ch.cv:
            ch.events[:] = [e for e in ch.events if not (e.get("sessionId") == s and e.get("method") == "Page.loadEventFired")]
        nav = ch.send("Page.navigate", {"url": url}, session=s)
        if nav.get("errorText"):  # a missing file or a refused port answers here, not with a load event
            raise MeasureError(f"{url}: {nav['errorText']}")
        if not ch.wait_event("Page.loadEventFired", s, timeout=40):
            raise MeasureError(f"{url}: no load event in 40 s")
        check_styles(ch, s)  # before the sweep and the wait, so both run on the styled page
        evaluate(ch, s, "document.fonts.ready.then(() => true)")
        sweep = evaluate(ch, s, SWEEP_JS, timeout=60)
        settle = evaluate(ch, s, SETTLE_JS, timeout=SETTLE_CAP_MS / 1000 + 15)
        check_styles(ch, s)  # again at the read: a sheet the page swapped in late, or took away
        d = evaluate(ch, s, probe_src, timeout=60)
        d["settle"] = dict(settle, loading=sweep["loading"])
        return d
    finally:
        ch.close_page(s)
