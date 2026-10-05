"""Judge the boxes a probe measured on a rendered page.

Everything here is pure: it takes the JSON the in-page probe returns (one
object per viewport) and gives back table rows, so every rule is tested on
recorded probes with no browser.

A probe lists every repeated set on the page: a parent with three or more
visible element children of one tag. Each child is a row, and a row's cells
are matched across rows by position and tag. The rules, with the Galen
Framework spec each one borrows its meaning from:

  columns      (aligned vertically left / right, centered)  every cell column
               shares a left or a right edge (a top or bottom edge for a
               side-by-side set), or its centre line when the set's CSS
               centres its members; a cell's leading mark (a status dot, an
               icon) is a sub-column
  gaps         (below / above, in px)    the gaps between neighbouring rows
               are equal
  gap-scale                              each gap sits on the spacing scale
  equal-size   (width / height)          rows are the same height (stacked)
               or width (side by side)
  baselines                              text cells on one line share their
               first line's baseline
  viewport     (inside)                  nothing is wider than the viewport
  screen-height                          with --screen, no page scroll

Every rule allows TOL px. A FAIL row carries the measured numbers.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

TOL = 1.0      # every rule's tolerance, px
OVERLAP = 2.0  # how far neighbouring rows may overlap and still count as stacked

Scale = Union[int, frozenset]  # a grid step in px, or the set of allowed gaps
Row = Dict[str, str]
Allow = Tuple[str, str]


def on_scale(gap: float, scale: Scale) -> bool:
    """A gap rounded to the pixel is on the scale; zero always is."""
    r = round(gap)
    if r == 0:
        return True
    if isinstance(scale, int):
        return r % scale == 0
    return float(r) in scale


def fmt(v: Optional[float]) -> str:
    return ("%.2f" % v).rstrip("0").rstrip(".") if v is not None else "none"


def spread(vals: List[float]) -> float:
    return max(vals) - min(vals) if vals else 0.0


def rows_label(ix: Iterable[int]) -> str:
    ix = list(dict.fromkeys(ix))  # a wrapped line names its row once for all its screen lines
    more = f" (+{len(ix) - 12} more)" if len(ix) > 12 else ""
    return ("row " if len(ix) == 1 else "rows ") + ", ".join(str(i) for i in ix[:12]) + more


def offenders(vals: List[float], idx: List[int]) -> str:
    """Which rows break the line: those more than TOL off the value most rows
    share (to the half pixel). When no two rows share a value there is no line
    to be off, so every row is named. When two values tie for the most rows
    (49,57,49,57) neither is the line, and no row is named off it."""
    top = Counter(round(v * 2) / 2 for v in vals).most_common()
    m, n = top[0]
    if n < 2:
        return f"{rows_label(idx)} share no value"
    if len(top) > 1 and top[1][1] == n:
        return f"no majority ({', '.join(fmt(v) + 'px' for v, k in top if k == n)} tie at {n} rows each)"
    return f"{rows_label(idx[i] for i, v in enumerate(vals) if abs(v - m) > TOL)} off {fmt(m)}px"


def band(c: Dict[str, Any]) -> Tuple[float, float]:
    """A text cell's first line as a band, a font size above its baseline to
    0.3 of one below. A baseline belongs to a line, not to the cell's box."""
    return c["baseline"] - c["fs"], c["baseline"] + 0.3 * c["fs"]


def same_line(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Two text cells read as one line when their first-line bands overlap by
    at least half the smaller band. A label beside a paragraph pairs with the
    paragraph's first line, never its second."""
    (a0, a1), (b0, b1) = band(a), band(b)
    return min(a1, b1) - max(a0, b0) >= 0.5 * min(a1 - a0, b1 - b0)


def one_line(r: Dict[str, Any]) -> bool:
    """A row that reads as one line of text: every text cell is one line and
    all of them sit on one band. A card's title above its body is two bands."""
    t = [c for c in r["cols"] if c.get("text")]
    if not all((c.get("lines") or 1) <= 1 and c.get("baseline") is not None and c.get("fs") for c in t):
        return False
    return all(same_line(a, b) for a in t for b in t)


def wrapped_row(r: Dict[str, Any], words: bool) -> bool:
    """A row is wrapped at this width when any cell is over one line. In a set
    of word lines it is also wrapped when its box is taller than 1.5 lines of
    its first cell, because a heading breaks between its one-line words. That
    second test is for word lines only: a padded list row is one line of
    reading, and calling it wrapped would silence equal-size on every list."""
    if any((c.get("lines") or 1) > 1 for c in r["cells"]):
        return True
    c0 = r["cells"][0]
    return bool(words and c0.get("lines") and r["box"]["h"] > 1.5 * c0["box"]["h"] / c0["lines"])


def screen_lines(cells: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """A word line's cells split where it wraps: a cell starts a new screen
    line when its top is at or below the middle of the cell before it. Read
    from boxes, never baselines, which can misplace a wrapped word."""
    out = [[cells[0]]]
    for p, c in zip(cells, cells[1:]):
        if c["box"]["y"] >= p["box"]["y"] + p["box"]["h"] / 2:
            out.append([c])
        else:
            out[-1].append(c)
    return out


def shared_edge(p: Dict[str, Any], n: Dict[str, Any]) -> float:
    """Rows may overlap by 2px, or by the wider of their borders, and still be
    stacked, so rows that share one border (margin-top: -1px) are a list."""
    return max(OVERLAP, p.get("border") or 0, n.get("border") or 0)


def orientation(rows: List[Dict[str, Any]]) -> Optional[str]:
    """'vertical' when the rows stack, 'horizontal' when they sit side by
    side, None for a wrapped grid."""
    def clear(key: str, size: str) -> bool:
        s = sorted(rows, key=lambda r: r["box"][key])
        return all(n["box"][key] >= p["box"][key] + p["box"][size] - shared_edge(p, n) - 0.005
                   for p, n in zip(s, s[1:]))
    if clear("y", "h"):
        return "vertical"
    if clear("x", "w"):
        return "horizontal"
    return None


def cell_tag(c: Dict[str, Any]) -> str:
    """Cells match by position and tag; classes are carried for reading only.
    A th and a td are one kind of cell."""
    t = c["sig"].split(".", 1)[0]
    return "td" if t == "th" else t


def common(sigs: Iterable[Any]) -> Any:
    return Counter(sigs).most_common(1)[0][0]


def left_columns(members: List[Tuple[int, Dict[str, Any]]]) -> List[Tuple[int, List[Tuple[int, Dict[str, Any]]]]]:
    """A wrapped grid's items grouped into columns by left edge, within TOL:
    (column number, items) for every column holding two items or more."""
    cols: List[List[Tuple[int, Dict[str, Any]]]] = []
    for m in sorted(members, key=lambda m: m[1]["box"]["x"]):
        if cols and abs(m[1]["box"]["x"] - cols[-1][0][1]["box"]["x"]) <= TOL:
            cols[-1].append(m)
        else:
            cols.append([m])
    return [(n, sorted(c, key=lambda m: m[0])) for n, c in enumerate(cols, 1) if len(c) >= 2]


def judge_set(st: Dict[str, Any], scale: Scale) -> Tuple[List[Row], List[Allow], bool, int]:
    """One repeated set -> (table rows, allows, judged?, rows skipped)."""
    # A flow word (a heading line's words after its first) is no column: columns
    # and equal-size read a row's `cols`, baselines reads every cell.
    rows = [dict(r, cols=[c for c in r["cells"] if not c.get("flow")]) for r in st["rows"]]
    words = any(c.get("flow") for r in rows for c in r["cells"])
    lines = words and all(len(r["cols"]) == 1 for r in rows)
    seqs = [tuple(cell_tag(c) for c in r["cols"]) for r in rows]
    major = common(seqs)
    everyone = list(enumerate(rows, 1))
    judged = [(i, r) for i, r in everyone if seqs[i - 1] == major]
    skipped = len(rows) - len(judged)
    allows: List[Allow] = [(st["path"], f'data-ruler="vary-{st["vary"]}"')] if st.get("vary") else []
    if len(judged) < 2:
        return [], allows, False, skipped
    nrows = f"{len(judged)}" + (f" (+{skipped} skipped)" if skipped else "")
    out: List[Row] = []

    def row(rule: str, meas: str, verdict: str) -> None:
        out.append({"set": st["path"], "rows": nrows, "rule": rule, "measurement": meas, "verdict": verdict})

    # Direction and gaps read every visible row: a row skipped for its odd
    # cells still stands in the list, and leaving it out would invent a gap.
    orient = orientation([r for _, r in everyone])
    in_table = all(r.get("tag") == "tr" for r in rows)

    def edges(boxes: List[Dict[str, float]], idx: List[int], label: str, vertical: bool,
              align: Optional[str] = None) -> None:
        k0, k1, e0, e1 = ("x", "w", "left", "right") if vertical else ("y", "h", "top", "bottom")
        a = [b[k0] for b in boxes]
        b = [b[k0] + b[k1] for b in boxes]
        # A centre line holds a column too (32px icons beside a 40px button in
        # a toolbar), but only where the CSS centres the set: elsewhere an
        # even inset on both sides is a defect the centre line would hide.
        c = [x[k0] + x[k1] / 2 for x in boxes]
        sa, sb, sc = spread(a), spread(b), spread(c)
        meas = f"{label}: {e0} spread {sa:.2f}px, {e1} spread {sb:.2f}px"
        if align:
            # Word lines: each box is a line's whole extent, and the text-align
            # that places the words names the one edge judged.
            vals, edge = {"left": (a, "left edges"), "right": (b, "right edges"), "center": (c, "centre lines")}[align]
            meas += (f", centre spread {sc:.2f}px" if align == "center" else "") \
                + f"; the line's extent judged on {edge} (text-align {align})"
            if spread(vals) <= TOL:
                row("columns", meas, "PASS")
            else:
                row("columns", f"{meas}; {edge} {','.join(fmt(v) for v in vals)}; {offenders(vals, idx)}", "FAIL")
            return
        if min(sa, sb) <= TOL:
            row("columns", meas, "PASS")
        elif sc <= TOL and st.get("centred"):
            row("columns", f"{meas}, centre spread {sc:.2f}px (the centres hold)", "PASS")
        else:
            vals, edge = (a, e0) if sa <= sb else (b, e1)
            why = " (the set does not centre its members)" if sc <= TOL else ""
            row("columns", f"{meas}, centre spread {sc:.2f}px{why}; {edge} edges "
                f"{','.join(fmt(v) for v in vals)}; {offenders(vals, idx)}", "FAIL")

    def columns(members: List[Tuple[int, Dict[str, Any]]], vertical: bool, prefix: str = "") -> None:
        for k in range(len(major)):
            cells = [r["cols"][k] for _, r in members]
            label = f"{prefix}col {k + 1} {common(c['sig'] for c in cells)}"
            if lines and vertical:
                # Each screen line's extent, its first cell's left edge to its
                # last cell's right edge: a centred heading's lines share a
                # centre, not an edge.
                ext = [(i, seg[0]["box"], seg[-1]["box"]) for i, r in members for seg in screen_lines(r["cells"])]
                edges([{"x": f["x"], "w": last["x"] + last["w"] - f["x"]} for _, f, last in ext],
                      [i for i, _, _ in ext], label, vertical, st.get("align", "left"))
            else:
                edges([c["box"] for c in cells], [i for i, _ in members], label, vertical)
            marked = [(i, r["cols"][k]["mark"]) for i, r in members if r["cols"][k].get("mark")]
            if marked:
                mtag = common(m["sig"].split(".", 1)[0] for _, m in marked)
                marked = [(i, m) for i, m in marked if m["sig"].split(".", 1)[0] == mtag]
            if len(marked) >= 2:
                edges([m["box"] for _, m in marked], [i for i, _ in marked],
                      f"{prefix}col {k + 1}/mark {common(m['sig'] for _, m in marked)}", vertical)

    if orient:
        columns(judged, orient == "vertical")
    else:
        # A wrapped grid has no one direction: its columns are the items that
        # share a left edge, each read like a stacked set.
        grid = left_columns(judged)
        for n, members in grid:
            columns(members, True, f"grid col {n} ({rows_label(i for i, _ in members)}) ")
        if not grid:
            row("columns", "not judged: a wrapped grid with no two items on one left edge", "SKIP")

    # Gaps. A table's row gaps are its border-spacing, never a spacing step.
    if in_table:
        row("gaps", "not judged: the gaps between table rows are its border-spacing", "SKIP")
    elif not orient:
        row("gaps", "not judged: a wrapped grid has no one direction (columns reads it by left edge)", "SKIP")
    else:
        key, size = ("y", "h") if orient == "vertical" else ("x", "w")
        order = sorted(everyone, key=lambda t: t[1]["box"][key])
        # A gap is read only between neighbours of one run: a visible sibling
        # outside the set between them (a heading between items) owns that space.
        pairs = [(p, n) for p, n in zip(order, order[1:]) if p[1].get("run") == n[1].get("run")]
        runs = len({r.get("run") for _, r in everyone})
        split = f"; read inside {runs} runs split by siblings outside the set" if runs > 1 else ""
        gaps = [n["box"][key] - (p["box"][key] + p["box"][size]) for (_, p), (_, n) in pairs]
        after = [i for (i, _), _ in pairs]
        glist = ",".join(fmt(round(g, 2)) for g in gaps) + "px"
        uneven = spread(gaps) > TOL
        # A negative gap no deeper than the shared edge is one border drawn once.
        offs = [(i, g) for i, g, ((_, p), (_, n)) in zip(after, gaps, pairs)
                if not on_scale(g, scale) and not (-shared_edge(p, n) - 0.005 <= g < 0)]
        if not pairs:
            row("gaps", "not judged: a sibling outside the set sits between every two members", "SKIP")
        if uneven:
            row("gaps", f"gaps {glist}{split}; the gap after {offenders(gaps, after)}", "FAIL")
        if offs:
            row("gap-scale", f"gaps {glist}{split}; off the scale after " + rows_label(i for i, _ in offs)
                + " (" + ", ".join(fmt(round(g)) + "px" for _, g in offs) + ")", "FAIL")
        if pairs and not uneven and not offs:
            row("gaps", f"gaps {glist}{split}", "PASS")

    # Equal size, judged only where every row is one line at this width: a
    # name that wraps on a phone makes its row taller by design.
    if not orient:
        row("equal-size", "not judged: a wrapped grid has no one direction", "SKIP")
    else:
        # A first or last row whose class differs from the majority's is a
        # header or footer, shorter by design, and is left out. In the middle
        # (a zebra stripe, a selected row) it is still compared. A majority is
        # more than half the rows; a half-and-half zebra list has none.
        msig, n = Counter(r.get("sig") for _, r in judged).most_common(1)[0]
        ends = (1, len(rows))
        peers = [(i, r) for i, r in judged if r.get("sig") == msig or i not in ends] if 2 * n > len(judged) else judged
        idx = [i for i, _ in peers]
        apart = sorted({i for i, _ in judged} - set(idx))
        note = f" ({rows_label(apart)} not compared: class differs from the majority {msig})" if apart else ""
        # Side-by-side links and chips are as wide as their words: a
        # side-by-side set whose every row is one line of text skips its
        # widths (columns checks its edges) and compares its heights.
        by_text = orient == "horizontal" and any(c.get("text") for _, r in judged for c in r["cols"])
        follows = by_text and all(one_line(r) for _, r in peers)

        def equal(dim: str, word: str) -> None:
            vals = [r["box"][dim] for _, r in peers]
            meas = f"{word} {','.join(fmt(v) for v in vals)}px{note}"
            if spread(vals) <= TOL:
                row("equal-size", meas, "PASS")
            elif dim == "w" and follows:
                row("equal-size", meas + "; not judged: widths follow the text (columns checks its edges)", "SKIP")
            elif dim == "w" and len(major) == 1 and not by_text:
                row("equal-size", meas + "; not judged: side-by-side single-cell set (columns checks its edges)", "SKIP")
            elif st.get("vary") == ("height" if dim == "h" else "width"):
                row("equal-size", meas + f' (declared data-ruler="vary-{st["vary"]}")', "ALLOW")
            else:
                row("equal-size", f"{meas}; {offenders(vals, idx)}", "FAIL")

        wrapped = [i for i, r in peers if wrapped_row(r, words)]
        dim, word = ("h", "heights") if orient == "vertical" else ("w", "widths")
        if wrapped:
            vals = [r["box"][dim] for _, r in peers]
            row("equal-size", f"{word} {','.join(fmt(v) for v in vals)}px{note}; not judged: wrapped at this width "
                f"({rows_label(wrapped)} over one line)", "SKIP")
        else:
            equal(dim, word)
            if by_text:
                equal("h", "heights")

    # Baselines: within a row, text cells on one line share its baseline.
    worst, checked, bad_rows, multi = 0.0, 0, [], 0
    for i, r in judged:
        cells = [c for c in r["cells"] if c.get("text") and c.get("baseline") is not None]
        if any(not c.get("fs") for c in cells):  # no band can be drawn, so never a silent pass
            raise ValueError(f"{st['path']}: a text cell has no font size (fs); re-record the probe")
        multi += len(cells) >= 2
        groups: List[List[Dict[str, Any]]] = []  # clusters of cells linked by same_line()
        for c in cells:
            hit = [g for g in groups if any(same_line(c, o) for o in g)]
            merged = [c] + [o for g in hit for o in g]
            groups = [g for g in groups if g not in hit] + [merged]
        for g in groups:
            if len(g) < 2:
                continue
            checked += 1
            g = sorted(g, key=lambda c: c["box"]["x"])
            bl = [c["baseline"] for c in g]
            worst = max(worst, spread(bl))
            if spread(bl) > TOL:
                bad_rows.append((i, g))
    if bad_rows:
        # Offsets from the row's leftmost text cell, not absolute y values:
        # the difference is the defect, and it does not move with the font.
        def offsets(g: List[Dict[str, Any]]) -> str:
            off = [(c["sig"], round(c["baseline"] - g[0]["baseline"], 2)) for c in g[1:]]
            return ", ".join(f"{sig} {'+' if d > 0 else ''}{fmt(d)}px" for sig, d in off if d) + f" from {g[0]['sig']}"
        detail = "; ".join(f"row {i} {offsets(g)}" for i, g in bad_rows[:6])
        more = f"; +{len(bad_rows) - 6} more rows" if len(bad_rows) > 6 else ""
        row("baselines", f"spread {worst:.2f}px; {detail}{more}", "FAIL")
    elif checked:
        row("baselines", f"level in {checked} text group(s), max spread {worst:.2f}px", "PASS")
    elif multi:
        row("baselines", f"no two text cells share a line in {multi} row(s) (their first-line bands sit apart)", "PASS")
    return out, allows, True, skipped


def check_probe(d: Any) -> None:
    """Raise ValueError naming the first field a recorded probe gets wrong.

    The judge trusts the shape the probe returns; a file from another driver
    or an edited recording is checked here first, so a bad one is reported
    by its path in the JSON instead of failing somewhere inside a rule."""
    def number(v: Any, where: str, optional: bool = False) -> None:
        if v is None and optional:
            return
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{where} is not a number")
        if not math.isfinite(v):  # JSON from a script can carry NaN, and NaN compares false with every edge
            raise ValueError(f"{where} is not finite")

    def obj(v: Any, where: str) -> Dict[str, Any]:
        if not isinstance(v, dict):
            raise ValueError(f"{where} is not an object")
        return v

    def items(v: Any, where: str, nonempty: bool = False) -> List[Any]:
        if not isinstance(v, list):
            raise ValueError(f"{where} is not a list")
        if nonempty and not v:
            raise ValueError(f"{where} is empty")
        return v

    def field(o: Dict[str, Any], key: str, where: str) -> Any:
        if key not in o:
            raise ValueError(f"{where}{key} is missing")
        return o[key]

    def box(o: Dict[str, Any], where: str) -> None:
        b = obj(field(o, "box", where + "."), where + ".box")
        for k in ("x", "y", "w", "h"):
            number(field(b, k, where + ".box."), f"{where}.box.{k}")

    def text(o: Dict[str, Any], key: str, where: str) -> None:
        if not isinstance(field(o, key, where + "."), str):
            raise ValueError(f"{where}.{key} is not text")

    if not isinstance(d, dict):
        raise ValueError("the probe is not an object")
    vp = obj(field(d, "viewport", ""), "viewport")
    for k in ("w", "h"):
        number(field(vp, k, "viewport."), f"viewport.{k}")
    for k in ("scrollWidth", "scrollHeight"):
        number(field(d, k, ""), k)
    for i, st in enumerate(items(d.get("sets") or [], "sets")):
        sw = f"sets[{i}]"
        text(obj(st, sw), "path", sw)
        for j, r in enumerate(items(field(st, "rows", sw + "."), sw + ".rows", nonempty=True)):
            rw = f"{sw}.rows[{j}]"
            box(obj(r, rw), rw)
            number(r.get("border"), f"{rw}.border", optional=True)
            for k, c in enumerate(items(field(r, "cells", rw + "."), rw + ".cells", nonempty=True)):
                cw = f"{rw}.cells[{k}]"
                text(obj(c, cw), "sig", cw)
                box(c, cw)
                for key in ("baseline", "fs", "lines"):
                    number(c.get(key), f"{cw}.{key}", optional=True)
                if c.get("mark") is not None:
                    text(obj(c["mark"], cw + ".mark"), "sig", cw + ".mark")
                    box(c["mark"], cw + ".mark")
    for i, o in enumerate(items(d.get("overflow") or [], "overflow")):
        text(obj(o, f"overflow[{i}]"), "path", f"overflow[{i}]")
        box(o, f"overflow[{i}]")
    off = d.get("off")
    if off is not None and (isinstance(off, bool) or not isinstance(off, int) or off < 0):
        raise ValueError("off is not a whole number of 0 or more")
    if d.get("reach") is not None:
        reach = obj(d["reach"], "reach")
        for k in ("right", "bottom"):
            number(reach.get(k), f"reach.{k}", optional=True)


def judge_viewport(d: Dict[str, Any], scale: Scale, screen: bool = False) -> Tuple[List[Row], List[Allow], int, int]:
    """One probe -> (table rows, allows, sets judged, rows skipped)."""
    table: List[Row] = []
    allows: List[Allow] = []
    sets = skipped = 0
    for st in d.get("sets") or []:
        t, a, judged, sk = judge_set(st, scale)
        table += t
        allows += a
        skipped += sk
        sets += judged
    vw, vh = d["viewport"]["w"], d["viewport"]["h"]
    ov = d.get("overflow") or []
    meas = f"scrollWidth {d['scrollWidth']} vs {vw}; {len(ov)} box(es) outside"
    if ov:
        meas += ": " + "; ".join(f"{o['path']} x {fmt(o['box']['x'])}..{fmt(o['box']['x'] + o['box']['w'])}" for o in ov[:8])
    # One pixel of scroll is forgiven only when it is a rounding: a page with
    # no viewport meta lays out at 980px on a phone and reports scrollWidth 981
    # while its widest box ends at 980. The probe sends `reach` (the furthest
    # visible box edge) only inside that pixel; a 376px bar on a 375px screen
    # is a real scroll.
    reach = d.get("reach") or {}

    def fits(scroll: float, size: float, key: str) -> bool:
        return scroll <= size or (scroll <= size + TOL and key in reach and reach[key] <= size + 0.5)

    if "right" in reach:
        meas += f"; widest box ends at {fmt(reach['right'])}"
    ok = fits(d["scrollWidth"], vw, "right") and not ov
    table.append({"set": "page", "rows": "-", "rule": "viewport", "measurement": meas, "verdict": "PASS" if ok else "FAIL"})
    if screen or d.get("screen"):
        ok = fits(d["scrollHeight"], vh, "bottom")
        smeas = f"scrollHeight {d['scrollHeight']} vs {vh}" + (f"; lowest box ends at {fmt(reach['bottom'])}" if "bottom" in reach else "")
        table.append({"set": "page", "rows": "-", "rule": "screen-height", "measurement": smeas, "verdict": "PASS" if ok else "FAIL"})
    off = int(d.get("off") or 0)  # each data-ruler="off" subtree is its own allow
    allows += [(f"subtree {n} of {off}", 'data-ruler="off"') for n in range(1, off + 1)]
    return table, allows, sets, skipped
