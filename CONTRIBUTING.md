# Contributing

Welcome things:

- A page the ruler reads wrong: a defect it misses, or a designed layout it
  fails. The smallest HTML that shows it is the most useful bug report there
  is, because it becomes a fixture.
- Fixes to the probe's set detection, with the fixture that proves them.
- Fixes to anything the README claims that turns out not to be true.

Ground rules: the package stays standard-library only, every rule change
ships with a fixture page and its recorded probe, and assertions are on the
exact measurement string a row carries. Keep
`python -m unittest discover -s tests -v` green.

Recording a fixture: put the page in `tests/fixtures/<name>.html`, then

```bash
python -m layout_ruler tests/fixtures/<name>.html --viewport 1280x900 --dump-probe /tmp/probe
mv /tmp/probe/<name>-1280x900.json tests/fixtures/<name>.json
```

and add `<name>` to the table in `tests/test_calibration.py` with the rules it
must fail. A fixture recorded at 375x812 is saved as `<name>-375.json`. The
recordings depend on the fonts of the machine that made them, so the unit
tests judge recordings and never re-render them.

After a change to the output, regenerate the demo session with
`UPDATE_DEMO_TRANSCRIPT=1 python -m unittest discover -s tests -p test_demo_transcript.py`
and commit the new `demo/transcript.json`. The demo pages set every size in
whole CSS pixels so their numbers hold on any platform; keep it that way.
