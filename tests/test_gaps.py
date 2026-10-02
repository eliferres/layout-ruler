"""The gaps and gap-scale rules: neighbouring rows sit an equal distance
apart, and every distance is a step on the spacing scale."""
from __future__ import annotations

import unittest

from support import failing, find, probe, rows


class TestGaps(unittest.TestCase):
    def test_an_uneven_gap_fails_both_rules_with_every_gap_printed(self) -> None:
        table = rows("uneven-gaps")
        self.assertEqual(find(table, "gaps", "FAIL")["measurement"],
                         "gaps 12,12,18,12px; the gap after row 3 off 12px")
        self.assertEqual(find(table, "gap-scale", "FAIL")["measurement"],
                         "gaps 12,12,18,12px; off the scale after row 3 (18px)")

    def test_the_grid_step_decides_the_scale(self) -> None:
        self.assertEqual(failing("uneven-gaps", scale=6), ["gaps"])
        self.assertEqual(failing("aligned-list", scale=5), [])  # zero gaps are on every scale

    def test_an_explicit_scale_replaces_the_grid(self) -> None:
        self.assertEqual(failing("uneven-gaps", scale=frozenset({12.0, 18.0})), ["gaps"])
        self.assertEqual(failing("uneven-gaps", scale=frozenset({12.0})), ["gap-scale", "gaps"])

    def test_rows_sharing_one_border_still_stack(self) -> None:
        """A -1px gap is one border drawn once, not a spacing step."""
        self.assertIsNotNone(find(rows("shared-border-rows"), "gaps", "PASS", "gaps -1,-1,-1,-1px"))

    def test_a_skipped_row_still_stands_in_the_list(self) -> None:
        """Leaving the odd row out would invent one double gap."""
        row = find(rows("skipped-middle-row"), "gaps", "PASS")
        self.assertEqual((row["rows"], row["measurement"]), ("4 (+1 skipped)", "gaps 8,8,8,8px"))

    def test_a_heading_between_items_splits_the_runs(self) -> None:
        row = find(rows("heading-between-items"), "gaps", "PASS")
        self.assertEqual(row["measurement"], "gaps 16,16px; read inside 2 runs split by siblings outside the set")

    def test_table_rows_and_wrapped_grids_say_why_they_are_skipped(self) -> None:
        self.assertIsNotNone(find(rows("table-dot-column"), "gaps", "SKIP", "not judged: the gaps between table rows"))
        self.assertIsNotNone(find(rows("wrapped-card-grid"), "gaps", "SKIP", "not judged: a wrapped grid"))

    def test_padded_inline_links_are_controls_and_keep_their_gaps_judged(self) -> None:
        self.assertEqual(find(rows("inline-nav-links"), "gaps", "FAIL")["measurement"],
                         "gaps 8,20,8px; the gap after row 2 off 8px")

    def test_words_in_text_flow_are_never_a_set(self) -> None:
        """A space between two words is no gap on the scale."""
        # The sets are the heading's lines, each holding its words as cells.
        lines = probe("right-set-heading")["sets"]
        self.assertTrue(lines and all(len(r["cells"]) >= 2 for s in lines for r in s["rows"]))
        self.assertEqual([r for r in rows("one-line-hero") if r["rule"] == "gaps"], [])


if __name__ == "__main__":
    unittest.main()
