"""Which linked stylesheets a page is missing, decided from the page's lists
and the DevTools network events, with no browser. A page measured without
its styles would be judged on browser defaults."""
from __future__ import annotations

import unittest

from layout_ruler.chrome import missing_sheets

S, A, B = "sess", "https://example.test/a.css", "https://example.test/b.css"


def req(rid: int, url: str, s: str = S) -> dict:
    return {"sessionId": s, "method": "Network.requestWillBeSent", "params": {"requestId": rid, "request": {"url": url}}}


def resp(rid: int, status: int, mime: str = "text/css", header: bool = True) -> dict:
    """header: whether the server sent Content-Type (the protocol guesses mimeType otherwise)."""
    r = {"status": status, "mimeType": mime, "headers": {"content-type": mime + "; charset=utf-8"} if header else {}}
    return {"sessionId": S, "method": "Network.responseReceived", "params": {"requestId": rid, "response": r}}


def fin(rid: int) -> dict:
    return {"sessionId": S, "method": "Network.loadingFinished", "params": {"requestId": rid}}


def failed(rid: int, text: str = "net::ERR_FILE_NOT_FOUND", canceled: bool = False, s: str = S) -> dict:
    return {"sessionId": s, "method": "Network.loadingFailed",
            "params": {"requestId": rid, "errorText": text, "canceled": canceled}}


class TestMissingSheets(unittest.TestCase):
    def check(self, want: list, linked: list, pending: list, events: list, **kw: object) -> None:
        self.assertEqual(missing_sheets(linked, pending, events, S, **kw), want)

    def test_a_sheet_still_pending_after_the_wait_is_named(self) -> None:
        self.check([A + " (not loaded in 10 s)"], [A], [A], [])

    def test_a_failed_file_sheet_is_named_though_chrome_gives_it_an_empty_sheet(self) -> None:
        self.check([A + " (net::ERR_FILE_NOT_FOUND)"], [A, B], [], [req(1, A), failed(1), req(2, B), resp(2, 200), fin(2)])

    def test_http_errors_are_named(self) -> None:
        self.check([A + " (HTTP 404)"], [A], [], [req(1, A), resp(1, 404), fin(1)])
        self.check([A + " (HTTP 503)"], [A], [A], [req(1, A), resp(1, 503)])

    def test_a_cancelled_request_counts_neither_way(self) -> None:
        self.check([], [A], [], [req(1, A), failed(1, "net::ERR_ABORTED", canceled=True)])

    def test_a_failure_then_a_success_is_loaded(self) -> None:
        self.check([], [A], [], [req(1, A), failed(1), req(2, A), resp(2, 200), fin(2)])

    def test_a_redirect_to_a_404_names_the_linked_url(self) -> None:
        self.check([A + " (HTTP 404)"], [A], [], [req(1, A), req(1, B), resp(1, 404), fin(1)])

    def test_unlinked_requests_and_other_tabs_never_count(self) -> None:
        self.check([], [A], [], [req(1, B), failed(1), req(2, A), resp(2, 200), fin(2)])
        self.check([], [A], [], [req(1, A, "other"), failed(1, s="other")])

    def test_a_sheet_linked_twice_is_named_once(self) -> None:
        self.check([A + " (net::ERR_FILE_NOT_FOUND)"], [A, A], [], [req(1, A), failed(1)])

    def test_an_html_error_page_sent_with_200_is_a_failed_sheet_outside_quirks_mode(self) -> None:
        events = [req(1, A), resp(1, 200, mime="text/html"), fin(1)]
        self.check([A + " (served as text/html, not text/css)"], [A], [], events)
        self.check([], [A], [], events, quirks=True)

    def test_only_a_type_the_server_sent_is_judged(self) -> None:
        self.check([], [A], [], [req(1, A), resp(1, 200, mime="text/plain", header=False), fin(1)])
        self.check([A + " (served as text/plain, not text/css)"], [A], [], [req(1, A), resp(1, 200, mime="text/plain"), fin(1)])

    def test_a_fragment_never_reaches_the_network(self) -> None:
        self.check([A + "#v2 (HTTP 404)"], [A + "#v2"], [], [req(1, A), resp(1, 404), fin(1)])

    def test_preload_swaps_are_read_on_the_network(self) -> None:
        self.check([B + " (HTTP 404)", A + " (net::ERR_FILE_NOT_FOUND)"], [B], [],
                   [req(1, A), failed(1), req(2, B), resp(2, 404), fin(2)], swaps=[A])
        self.check([A + " (not loaded in 10 s)"], [], [], [req(1, A)], swaps=[A])
        self.check([], [], [], [req(1, B), fin(1)], swaps=[A])  # never fetched: its media did not match
        self.check([], [], [], [req(1, A), resp(1, 200), fin(1)], swaps=[A])


if __name__ == "__main__":
    unittest.main()
