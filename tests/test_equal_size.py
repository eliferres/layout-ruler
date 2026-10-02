"""The equal-size rule: stacked rows share a height, side-by-side rows a width."""
from __future__ import annotations

import unittest

from support import edited, failing, find, rows


class TestEqualSize(unittest.TestCase):
    def test_a_taller_row_is_named_with_every_height(self) -> None:
        self.assertEqual(find(rows("unequal-heights"), "equal-size", "FAIL")["measurement"],
                         "heights 48,48,72,48,48px; row 3 off 48px")

    def test_a_declared_variance_is_an_allow_never_a_silent_pass(self) -> None:
        self.assertIsNotNone(find(rows("unequal-heights-vary"), "equal-size", "ALLOW"))

    def test_a_row_over_one_line_skips_the_rule_and_says_so(self) -> None:
        d = edited("unequal-heights")
        d["sets"][0]["rows"][2]["cells"][0]["lines"] = 2
        row = find(rows(d), "equal-size", "SKIP")
        self.assertTrue(row["measurement"].endswith("not judged: wrapped at this width (row 3 over one line)"))
        self.assertEqual(failing(d), [])

    def test_side_by_side_links_follow_their_text_in_width_but_not_height(self) -> None:
        table = rows("nav-widths")
        self.assertIsNotNone(find(table, "equal-size", "SKIP", "widths 37.05,90.69,50.69,41.81,78.27px"))
        self.assertIsNotNone(find(table, "equal-size", "PASS", "heights 44,44,44,44,44px"))
        self.assertEqual(find(rows("chip-band-tall"), "equal-size", "FAIL")["measurement"],
                         "heights 30,30,36,30,30px; row 3 off 30px")

    def test_a_header_row_at_either_end_is_left_out(self) -> None:
        row = find(rows("header-row"), "equal-size", "PASS")
        self.assertIn("(row 1 not compared: class differs from the majority div)", row["measurement"])

    def test_a_different_class_in_the_middle_is_still_compared(self) -> None:
        self.assertEqual(failing("zebra-five-rows"), ["equal-size"])
        self.assertEqual(failing("row-state-five-rows"), ["equal-size"])

    def test_side_by_side_cards_compare_their_heights(self) -> None:
        for name in ("landing-page", "feature-cards", "pricing-tiers-uneven"):
            with self.subTest(fixture=name):
                self.assertIn("equal-size", failing(name))


if __name__ == "__main__":
    unittest.main()
