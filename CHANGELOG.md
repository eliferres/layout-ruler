# Changelog

All notable changes to this project are documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-02

### Added

- `layout-ruler PAGE` renders an HTML file or URL in headless Chrome at 1280x900 and 375x812 and prints one line per finding with the measured pixels.
- The `columns` rule: cells down a list, table or grid share a left or right edge, and a leading dot or icon is checked as its own column.
- The `gaps` and `gap-scale` rules: neighbouring rows sit an equal distance apart, on a 4px grid or the scale given with `--grid` or `--scale`.
- The `equal-size` rule: stacked rows share a height and side-by-side rows a width, skipped with the reason where a row wraps.
- The `baselines` rule: text cells on one line of a row share its baseline, with the offset of each cell that does not.
- The `viewport` rule, and `screen-height` with `--screen`: nothing runs off the screen at any width checked.
- `data-ruler` attributes to declare a designed exception in the page, each listed in the output as an allow.
- `--json` output with every row, and `--probe-json` / `--dump-probe` to judge measurements recorded by any driver.
- Exit codes 0 for no findings, 1 for findings and 2 for a page that could not be measured, including one whose stylesheet did not load.
