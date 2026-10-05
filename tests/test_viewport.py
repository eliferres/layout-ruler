"""The viewport and screen-height rules: nothing runs off the screen."""
from __future__ import annotations

import unittest

from layout_ruler.judge import judge_viewport
from support import edited, failing, find, rows


def bar(scroll_width: int, reach: object = None, width: int = 375) -> dict:
    d = {"viewport": {"w": width, "h": 812}, "scrollWidth": scroll_width, "scrollHeight": 812,
         "sets": [], "overflow": [], "off": 0}
    if reach is not None:
        d["reach"] = reach
    return d


class TestViewport(unittest.TestCase):
    def test_a_wide_block_is_named_with_its_extent(self) -> None:
        self.assertEqual(find(rows("overflow"), "viewport", "FAIL")["measurement"],
                         "scrollWidth 1424 vs 1280; 1 box(es) outside: body > div.wide x 24..1424")

    def test_a_box_parked_off_the_start_edge_is_not_overflow(self) -> None:
        """A skip link at left: -9999px never scrolls the page sideways; in a
        right-to-left page the start edge is the right one, and overflow off
        the left does scroll."""
        self.assertEqual(failing("skip-link-off-left"), [])
        self.assertEqual(find(rows("rtl-overflow-left"), "viewport", "FAIL")["measurement"],
                         "scrollWidth 1424 vs 1280; 1 box(es) outside: body > div.wide x -144..1256")

    def test_one_pixel_of_rounding_is_forgiven_only_when_no_box_reaches_past(self) -> None:
        """A page with no viewport meta lays out at 980px on a phone and
        reports 981 while its widest box ends at 980."""
        self.assertEqual(failing(bar(981, {"right": 980}, width=980)), [])
        self.assertEqual(failing(bar(376, {"right": 376})), ["viewport"])
        self.assertEqual(failing(bar(376)), ["viewport"])           # no reach recorded: not forgiven
        self.assertEqual(failing(bar(377, {"right": 375})), ["viewport"])  # two pixels never are

    def test_a_376px_bar_fits_a_desktop_and_runs_off_a_phone(self) -> None:
        self.assertEqual(failing("one-px-bar"), [])
        self.assertEqual(find(rows("one-px-bar-375"), "viewport", "FAIL")["measurement"],
                         "scrollWidth 376 vs 375; 0 box(es) outside; widest box ends at 376")

    def test_screen_height_runs_only_when_asked(self) -> None:
        d = bar(375)
        d["scrollHeight"] = 900
        self.assertEqual(failing(d), [])
        self.assertEqual(failing(d, screen=True), ["screen-height"])
        d["screen"] = True  # data-ruler="screen" on the page asks too
        self.assertEqual(failing(d), ["screen-height"])

    def test_each_skipped_subtree_is_its_own_allow(self) -> None:
        _, allows, _, _ = judge_viewport(edited("off-twice"), 4)
        self.assertEqual(allows, [("subtree 1 of 2", 'data-ruler="off"'), ("subtree 2 of 2", 'data-ruler="off"')])


if __name__ == "__main__":
    unittest.main()
