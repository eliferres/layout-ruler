"""The columns rule: cells down a set share a left or right edge, or their
centre line when the CSS centres the set."""
from __future__ import annotations

import unittest

from support import edited, failing, find, rows


class TestColumns(unittest.TestCase):
    def test_ragged_status_dots_are_named_with_every_left_edge(self) -> None:
        """Each row its own grid with an auto column: the dot lands at a
        different x in every row, and the finding prints each one."""
        row = find(rows("ragged-list"), "columns", "FAIL")
        self.assertEqual(row["measurement"],
                         "col 2 span.dot: left spread 135.17px, right spread 135.17px, centre spread 135.17px; "
                         "left edges 84.47,218.75,125.97,185.83,83.58; rows 1, 2, 3, 4, 5 share no value")

    def test_a_rows_cells_are_never_a_set_of_their_own(self) -> None:
        sets = {r["set"] for r in rows("aligned-list")}
        self.assertEqual(sets, {"body > ul.list", "page"})

    def test_classes_never_split_rows(self) -> None:
        """A state class or a zebra class on some rows used to hide the list."""
        for name in ("row-state-class", "zebra-classes", "three-distinct-classes"):
            with self.subTest(fixture=name):
                self.assertIsNotNone(find(rows(name), "columns", "FAIL", "col 2 span.dot"))

    def test_a_dot_nested_in_a_table_cell_is_held_as_a_mark_column(self) -> None:
        table = rows("table-dot-column")
        self.assertIsNotNone(find(table, "columns", "FAIL", "col 2/mark i.dot: left spread 40.00px"))
        self.assertFalse(any(r["set"].endswith("> tr") for r in table), "a tr's cells were judged as a set")

    def test_a_right_aligned_pill_passes_while_its_dot_fails(self) -> None:
        table = rows("right-pill-dot")
        self.assertIsNotNone(find(table, "columns", "PASS", "col 2 span.status"))
        self.assertIsNotNone(find(table, "columns", "FAIL", "col 2/mark i.dot: left spread 113.83px"))

    def test_display_contents_is_see_through(self) -> None:
        self.assertIsNotNone(find(rows("contents-cell"), "columns", "FAIL", "col 2 span.dot"))
        self.assertEqual(failing("contents-row-wrapper"), ["columns"])

    def test_a_wrapped_grid_is_read_by_its_columns_of_items(self) -> None:
        table = rows("wrapped-card-grid")
        self.assertIsNotNone(find(table, "columns", "PASS", "grid col 1 (rows 1, 4) col 2 a.btn"))

    def test_a_card_drifting_inside_its_grid_column_fails_there(self) -> None:
        d = edited("wrapped-card-grid")
        for cell in d["sets"][0]["rows"][3]["cells"]:
            cell["box"]["x"] += 9
        self.assertIsNotNone(find(rows(d), "columns", "FAIL", "grid col 1 (rows 1, 4) col 1 p.t: left spread 9.00px"))

    def test_two_values_tied_for_most_rows_name_no_row(self) -> None:
        d = edited("zebra-classes")
        for n in (1, 3):
            d["sets"][0]["rows"][n]["cells"][0]["box"]["x"] += 8
        row = find(rows(d), "columns", "FAIL", "col 1 span.name")
        self.assertIn("left edges 40,48,40,48; no majority (40px, 48px tie at 2 rows each)", row["measurement"])

    def test_the_centre_line_holds_only_where_the_css_centres_the_set(self) -> None:
        self.assertEqual(failing("toolbar-centred"), [])
        d = edited("toolbar-centred")
        for s in d["sets"]:
            s.pop("centred", None)
        self.assertIn("columns", failing(d))
        self.assertIsNotNone(find(rows("even-inset-stack"), "columns", "FAIL"))
        self.assertIn("(the set does not centre its members)", find(rows("even-inset-stack"), "columns", "FAIL")["measurement"])

    def test_a_list_inside_a_card_is_judged_as_its_own_set(self) -> None:
        for name in ("cards-same-ragged-list", "cards-ragged-list"):
            with self.subTest(fixture=name):
                self.assertIsNotNone(find(rows(name), "columns", "FAIL", "col 2 span.dot"))

    def test_a_cards_own_title_meta_and_body_are_its_cells(self) -> None:
        for name in ("card-stack", "card-stack-deep", "card-stack-deeper", "card-list"):
            with self.subTest(fixture=name):
                self.assertEqual(failing(name), [])
        for name in ("card-list-title-drift", "card-list-heading-drift", "span-paragraph-card"):
            with self.subTest(fixture=name):
                self.assertEqual(failing(name), ["columns"])

    def test_a_trailing_arrow_after_the_wrappers_own_text_is_no_column(self) -> None:
        self.assertEqual(failing("arrow-links"), [])
        self.assertEqual(failing("trailing-icon"), [])
        # After a text span it is a column: a ragged dot after a name has that shape.
        self.assertEqual(failing("trailing-arrow-span"), ["columns"])

    def test_word_lines_are_judged_on_the_edge_their_text_align_names(self) -> None:
        row = find(rows("centred-heading-off"), "columns", "FAIL")
        self.assertIn("judged on centre lines (text-align center); centre lines 640,646,640; row 2 off 640px",
                      row["measurement"])
        self.assertEqual(failing("centred-heading-375"), [])

    def test_a_fixed_width_label_keeps_its_value_column_measured(self) -> None:
        self.assertEqual(failing("key-value"), [])
        self.assertEqual(failing("key-value-ragged"), ["columns"])
        self.assertEqual(failing("key-value-ragged-375"), ["columns"])

    def test_structured_p_rows_are_rows_like_their_div_twins(self) -> None:
        self.assertEqual(failing("receipt-p-rows"), failing("receipt-div-rows"))
        self.assertEqual(failing("receipt-total"), ["columns"])

    def test_a_framework_root_wrapper_stands_for_body(self) -> None:
        self.assertEqual(failing("root-react"), [])
        self.assertEqual(failing("app-root-sections"), [])
        self.assertEqual(failing("root-plain-wrapper"), ["columns", "equal-size"])


if __name__ == "__main__":
    unittest.main()
