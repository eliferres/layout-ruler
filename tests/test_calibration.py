"""Every recorded fixture keeps its verdict and fails on exactly its own rules.

A fixture that fails on the wrong rule proves nothing, so each entry names
the full set of failing rules, and an empty set means the page passes.
"""
from __future__ import annotations

import unittest

from layout_ruler.judge import check_probe
from support import FIXTURES, failing, probe

# name -> the rules that must FAIL (all of them, and no other)
EXPECTED = {
    "aligned-list": [],
    "ragged-list": ["columns"],
    "uneven-gaps": ["gap-scale", "gaps"],
    "unequal-heights": ["equal-size"],
    "unequal-heights-vary": [],
    "baseline-off": ["baselines"],
    "overflow": ["viewport"],
    "nav-widths": [],
    "stacked-beside-tall": [],
    "stacked-beside-tall-off": ["baselines"],
    "row-state-class": ["columns"],
    "zebra-classes": ["columns"],
    "three-distinct-classes": ["columns"],
    "shared-border-rows": ["columns"],
    "skipped-middle-row": [],
    "table-dot-column": ["columns"],
    "table-collapsed-borders": ["columns"],
    "right-pill-dot": ["columns"],
    "contents-row-wrapper": ["columns"],
    "contents-cell": ["columns"],
    "wrapped-card-grid": [],
    "off-twice": [],
    "cards-same-ragged-list": ["columns"],
    "cards-ragged-list": ["columns"],
    "cards-ragged-list-control": ["columns"],
    "mixed-shapes": ["columns"],
    "pill-in-cell": [],
    "heading-between-paragraphs": [],
    "heading-between-items": [],
    "header-row": [],
    "trailing-icon": [],
    "landing-page": ["columns", "equal-size"],
    "feature-cards": ["columns", "equal-size"],
    "grid-in-cell": ["columns"],
    "card-grid-3x3": ["columns"],
    "card-grid-3x3-headed": ["columns"],
    "card-stack": [],
    "card-stack-nowrap": [],
    "zebra-five-rows": ["equal-size"],
    "row-state-five-rows": ["equal-size"],
    "arrow-links": [],
    "text-with-dot": [],
    "trailing-arrow-span": ["columns"],
    "card-stack-deep": [],
    "card-stack-deeper": [],
    "pricing-mixed-items": ["columns"],
    "blog-feed": ["columns"],
    "form-rows": [],
    "toolbar-centred": [],
    "pill-block": [],
    "pill-deeper": [],
    "app-root-sections": [],
    "word-split-heading": [],
    "word-split-heading-375": [],
    "word-split-heading-ragged": ["columns"],
    "chip-band": [],
    "chip-band-tall": ["equal-size"],
    "pricing-tiers-uneven": ["equal-size"],
    "amounts-end-state": [],
    "amounts-end-state-off": ["columns"],
    "key-value": [],
    "key-value-ragged": ["columns"],
    "key-value-ragged-375": ["columns"],
    "price-list-ragged": ["columns"],
    "price-list-ragged-375": ["columns"],
    "word-split-natural": [],
    "word-split-ragged-five": ["columns"],
    "word-split-ragged-five-375": ["columns"],
    "word-rotator": [],
    "card-list": [],
    "card-list-two": [],
    "card-list-title-drift": ["columns"],
    "card-list-heading-drift": ["columns"],
    "article": [],
    "root-plain-wrapper": ["columns", "equal-size"],
    "root-react": [],
    "root-react-no-main": [],
    "even-inset-stack": ["columns"],
    "flex-start-row": ["columns", "equal-size"],
    "one-px-bar": [],
    "one-px-bar-375": ["viewport"],
    "grid-align-items-center": ["columns"],
    "sections-grid": ["columns"],
    "centred-heading": [],
    "centred-heading-375": [],
    "centred-heading-off": ["columns"],
    "changelog": [],
    "changelog-off": ["columns"],
    "icon-meta-list": [],
    "receipt-p-rows": ["columns"],
    "receipt-div-rows": ["columns"],
    "receipt-total": ["columns"],
    "span-paragraph-card": ["columns"],
    "right-set-heading": ["columns"],
    "two-line-hero": [],
    "one-line-hero": [],
    "inline-nav-links": ["columns", "gaps"],
    "skip-link-off-left": [],
    "rtl-overflow-left": ["viewport"],
}


class TestCalibration(unittest.TestCase):
    def test_every_fixture_fails_on_exactly_its_own_rules(self) -> None:
        for name, rules in EXPECTED.items():
            with self.subTest(fixture=name):
                self.assertEqual(failing(name), rules)

    def test_every_recorded_probe_is_in_the_table(self) -> None:
        recorded = {p.stem for p in FIXTURES.glob("*.json")}
        self.assertEqual(recorded, set(EXPECTED))

    def test_every_recorded_probe_has_the_shape_the_judge_reads(self) -> None:
        for name in EXPECTED:
            with self.subTest(fixture=name):
                check_probe(probe(name))

    def test_every_probe_has_its_page(self) -> None:
        for name in EXPECTED:
            page = name[:-4] if name.endswith("-375") else name
            with self.subTest(fixture=name):
                self.assertTrue((FIXTURES / f"{page}.html").is_file())

    def test_every_recorded_text_cell_carries_its_font_size(self) -> None:
        """The baselines rule draws a line's band from fs; a probe without it
        would pass that rule by silence."""
        for name in EXPECTED:
            d = probe(name)
            missing = [c for s in d["sets"] for r in s["rows"] for c in r["cells"] if c.get("text") and not c.get("fs")]
            with self.subTest(fixture=name):
                self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
