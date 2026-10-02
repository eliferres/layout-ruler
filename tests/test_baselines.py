"""The baselines rule: text cells on one line of a row share its baseline."""
from __future__ import annotations

import unittest

from layout_ruler.judge import judge_viewport
from support import edited, failing, find, rows


class TestBaselines(unittest.TestCase):
    def test_a_pushed_cell_prints_its_offset_from_the_rows_first_text_cell(self) -> None:
        """Offsets, not absolute y values: the difference is the defect, and
        it does not move when the font does."""
        self.assertEqual(find(rows("baseline-off"), "baselines", "FAIL")["measurement"],
                         "spread 6.00px; row 3 span.value +6px from span.name")

    def test_a_tall_cell_is_compared_with_the_stacks_first_line_only(self) -> None:
        self.assertEqual(find(rows("stacked-beside-tall"), "baselines", "PASS")["measurement"],
                         "level in 3 text group(s), max spread 0.00px")

    def test_the_same_pair_pushed_four_pixels_fails_in_every_row(self) -> None:
        row = find(rows("stacked-beside-tall-off"), "baselines", "FAIL")
        self.assertEqual(row["measurement"], "spread 4.00px; row 1 span.line -4px from span.tall; "
                         "row 2 span.line -4px from span.tall; row 3 span.line -4px from span.tall")

    def test_cells_that_share_no_line_say_so(self) -> None:
        self.assertIsNotNone(find(rows("wrapped-card-grid"), "baselines", "PASS", "no two text cells share a line"))

    def test_a_probe_without_font_sizes_is_refused(self) -> None:
        d = edited("aligned-list")
        for c in d["sets"][0]["rows"][0]["cells"]:
            c.pop("fs", None)
        with self.assertRaisesRegex(ValueError, "has no font size"):
            judge_viewport(d, 4)

    def test_a_tolerance_of_one_pixel(self) -> None:
        d = edited("aligned-list")
        d["sets"][0]["rows"][1]["cells"][3]["baseline"] += 1
        self.assertEqual(failing(d), [])
        d["sets"][0]["rows"][1]["cells"][3]["baseline"] += 0.5
        self.assertEqual(failing(d), ["baselines"])


if __name__ == "__main__":
    unittest.main()
