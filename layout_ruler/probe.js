// layout-ruler's in-page measurement. Plain browser JS with no bundler and no
// exports: the file is one expression that evaluates to the probe object.
// layout-ruler runs it through the DevTools protocol (Runtime.evaluate with
// returnByValue). Any other driver can run it too, for example Playwright's
// page.evaluate(fs.readFileSync('probe.js', 'utf8')), and hand the JSON to
// `layout-ruler --probe-json`; both get the same numbers.
//
// The contract the Python judge reads:
//   {"viewport":{"w":1280,"h":900},"scrollWidth":N,"scrollHeight":N,"screen":bool,
//    "sets":[{"path":"ul.list","vary":"height"|"width"|null,"centred":true?,"align":"right"|"center"?,
//             "rows":[{"tag":"li","sig":"li.row","run":0,"box":{"x","y","w","h"},"border":1,
//                      "cells":[{"sig":"span.name","box":{..},"baseline":411.5|null,"fs":16|null,
//                                "text":bool,"lines":1|null,"flow":true?,
//                                "mark":{"sig":"i.dot","box":{..}}|null}]}]}],
//    "overflow":[{"path":"div.hero","box":{..}}],"off":N,"reach":{"right":N,"bottom":N}?}
// Boxes are getBoundingClientRect() after scrollTo(0, 0), made page-relative
// and rounded to 0.01px. `fs` is the computed font size of the cell's first
// text, so the judge can draw that line's band. `lines` is the cell's content
// height over its line-height. `mark` is the cell's first leaf with no text
// that comes before its first text (a status dot, an icon). `sig` is tag plus
// sorted classes. `run` numbers the stretches of a set between siblings that
// are not members. `flow` marks a word after a row's first in a line of
// words. `off` counts the data-ruler="off" subtrees skipped. `reach` is sent
// only when the page scrolls by exactly one pixel (see the viewport rule).
//
// What counts as a repeated set: a parent with three or more visible element
// children sharing one tag. Classes never split rows (a zebra row or an
// .is-late state is still a row). A row's cells are its element children,
// matched by position, and are read once, as cells, never again as a set of
// their own. display: contents is see-through. A row whose only child is a
// wrapper (li > button > [name, status, amount]) is read through the wrapper,
// because that is where the cells a reader lines up actually are; the step
// down stops at a child that is itself a stacked list, which is judged as a
// set of its own. Page sections (section, article, header, footer, nav, main,
// aside) under body or main are the page's parts, never rows. A framework's
// lone root wrapper (div#__next, #root, #app, #__nuxt, #__layout, #svelte, or
// data-ruler="root") stands for body.
//
// The author speaks only to declare an exception: data-ruler="off" skips a
// subtree, data-ruler="vary-height" / "vary-width" on a set's parent declares
// a designed variance, data-ruler="screen" on html or body says the page must
// not scroll, data-ruler="root" marks a root wrapper.
(() => {
  window.scrollTo(0, 0);
  const sx = window.scrollX, sy = window.scrollY;
  const root = document.documentElement;
  // The layout viewport, never innerWidth: on a phone, content wider than the
  // screen makes the browser zoom out, and innerWidth then reports the zoomed
  // width (584 for a 375 screen), hiding the very overflow the rule exists for.
  const vw = root.clientWidth, vh = root.clientHeight;
  const SKIP = new Set(['SCRIPT', 'STYLE', 'TEMPLATE', 'OPTION']);
  const CLIPS = new Set(['hidden', 'clip', 'auto', 'scroll']);
  const r2 = (v) => Math.round(v * 100) / 100;
  const tokens = (el) => (el.getAttribute('data-ruler') || '').toLowerCase().split(/\s+/).filter(Boolean);
  const isOff = (el) => tokens(el).includes('off');
  const tag = (el) => el.tagName.toLowerCase();
  const sig = (el) => tag(el) + [...el.classList].sort().map((c) => '.' + c).join('');
  const boxOf = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r2(r.left + sx), y: r2(r.top + sy), w: r2(r.width), h: r2(r.height) };
  };
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  };
  // A readable label, not a selector engine: two classes per level (a
  // utility-class element would otherwise print forty), an id ends the walk,
  // at most three levels.
  const label = (el) => (el.id ? `${tag(el)}#${el.id}` : tag(el) + [...el.classList].slice(0, 2).map((c) => '.' + c).join(''));
  const path = (el) => {
    const parts = [];
    for (let e = el; e && e !== document.documentElement && parts.length < 3; e = e.parentElement) {
      parts.unshift(label(e));
      if (e.id || e === document.body) break;
    }
    return parts.join(' > ');
  };
  // An svg is one drawing: it can be a cell, but nothing inside it is
  // measured. A data-ruler="off" child is skipped and remembered in a Set, so
  // each subtree counts once however often it is passed.
  const offSeen = new Set();
  const childrenOf = (el) => {
    if (tag(el) === 'svg') return [];
    const out = [];
    for (const k of el.children) {
      if (SKIP.has(k.tagName)) continue;
      if (isOff(k)) { offSeen.add(k); continue; }
      if (getComputedStyle(k).display === 'contents') out.push(...childrenOf(k));
      else out.push(k);
    }
    return out;
  };
  const kids = (el) => childrenOf(el).filter(shown);
  const ownText = (el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  const borderOf = (el) => {
    const cs = getComputedStyle(el);
    return r2(Math.max(...['Top', 'Right', 'Bottom', 'Left'].map((s) => parseFloat(cs[`border${s}Width`]) || 0)));
  };
  // A line-height of `normal` is read as 1.2 font sizes, the browsers' usual default.
  const lineHeight = (el) => {
    const cs = getComputedStyle(el);
    return cs.lineHeight === 'normal' ? 1.2 * parseFloat(cs.fontSize) : parseFloat(cs.lineHeight);
  };
  // Lines by the content box: padding and borders are not lines.
  const linesOf = (el, box) => {
    const cs = getComputedStyle(el);
    const lh = lineHeight(el);
    const inner = box.h - ['paddingTop', 'paddingBottom', 'borderTopWidth', 'borderBottomWidth']
      .reduce((s, p) => s + (parseFloat(cs[p]) || 0), 0);
    return lh > 0 ? Math.max(1, Math.round(inner / lh)) : null;
  };
  // The first leaf inside a cell that carries no text, in document order: the
  // dot in a status pill, the icon in a button.
  const firstLeaf = (cell) => {
    for (const k of kids(cell)) {
      if (!kids(k).length) {
        if (tag(k) === 'svg' || !k.textContent.trim()) return k;
        continue;
      }
      const m = firstLeaf(k);
      if (m) return m;
    }
    return null;
  };
  // A mark leads its text: the dot before "Late" lines up down the column,
  // while an arrow after "Docs" sits wherever the word ends, by design. So the
  // leaf counts only when the cell's first text (t) comes after it.
  const markOf = (cell, t) => {
    const m = firstLeaf(cell);
    return m && (!t || m.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING) ? m : null;
  };
  const firstText = (cell) => {
    const w = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => {
        const p = n.parentElement;
        if (!n.textContent.trim() || !p || p.closest('svg') || SKIP.has(p.tagName)) return NodeFilter.FILTER_SKIP;
        return p.getClientRects().length && getComputedStyle(p).visibility !== 'hidden' ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
      },
    });
    return w.nextNode();
  };
  // The baseline, read the way a design tool draws it: a zero-size
  // inline-block sits on the baseline, so its top is the baseline's y. Text
  // that is a bare child of a flex or grid box is an anonymous item there, and
  // a marker beside it would become an item of its own, so the text is wrapped
  // in a plain span for the read (the same box the anonymous item had) and put
  // back. All in one batch: every style read, every marker in, every top read,
  // every marker out, so the page lays out once for the lot. A marker per cell,
  // each read between its own insert and remove, lays the page out once per
  // cell and timed out on a 2,000-row list.
  // Known limit: in a fixed-width inline-block whose text already overflows,
  // the marker adds a wrap point and that line's baseline reads a line low.
  const baselines = (pairs) => {
    const plans = new Map();
    for (const [, t] of pairs) {
      if (plans.has(t)) continue;
      const cs = getComputedStyle(t.parentNode);
      plans.set(t, { fs: r2(parseFloat(cs.fontSize)), flex: /flex|grid|box/.test(cs.display) });
    }
    for (const [t, p] of plans) {
      p.mark = document.createElement('span');
      p.mark.setAttribute('style', 'all:initial;display:inline-block;width:0;height:0;vertical-align:baseline');
      if (p.flex) {
        p.wrap = document.createElement('span');
        t.parentNode.insertBefore(p.wrap, t);
        p.wrap.appendChild(t);
        p.wrap.insertBefore(p.mark, t);
      } else {
        t.parentNode.insertBefore(p.mark, t);
      }
    }
    for (const p of plans.values()) p.top = r2(p.mark.getBoundingClientRect().top + sy);
    for (const [t, p] of plans) {
      p.mark.remove();
      if (p.wrap) { p.wrap.parentNode.insertBefore(t, p.wrap); p.wrap.remove(); }
    }
    for (const [cell, t] of pairs) Object.assign(cell, { baseline: plans.get(t).top, fs: plans.get(t).fs });
  };

  // The groups of three or more visible children sharing a tag, in the order
  // their tags first appear.
  const repeatedGroups = (el) => {
    const groups = new Map();
    for (const k of kids(el)) {
      if (!groups.has(tag(k))) groups.set(tag(k), []);
      groups.get(tag(k)).push(k);
    }
    return [...groups.entries()].filter(([, g]) => g.length >= 3);
  };
  // Do the members stack? The same test as the judge's orientation(): by top
  // edge, each clears the one above, allowed to overlap by 2px or by the wider
  // of their borders.
  const stacks = (members) => {
    const s = members.map((m) => ({ b: boxOf(m), e: borderOf(m) })).sort((a, b) => a.b.y - b.b.y);
    return s.every((n, i) => !i || n.b.y >= s[i - 1].b.y + s[i - 1].b.h - Math.max(2, s[i - 1].e, n.e) - 0.005);
  };
  // A nested list, never a card's own stack: at least three members share
  // one class signature, or one non-empty inner structure (the same child tag
  // sequence, as a list's items do). At least three, not all: a pricing list's
  // one odd item must not leave the whole list unjudged. A title, a meta line
  // and a body share neither, so they stay the row's cells.
  const listLike = (g) => {
    const three = (keys) => {
      const seen = new Map();
      return keys.some((k) => k !== '' && seen.set(k, (seen.get(k) || 0) + 1).get(k) >= 3);
    };
    return three(g.map(sig)) || three(g.map((k) => kids(k).map(tag).join(' ')));
  };
  const flexBox = (d) => d === 'flex' || d === 'inline-flex';
  const gridBox = (d) => d === 'grid' || d === 'inline-grid';
  const inlineLevel = (el) => getComputedStyle(el).display.startsWith('inline');
  // Prose is never a list: a card's title, meta line and body paragraphs are
  // its cells, so a title drifting 8px is measured. A prose-tag member is
  // prose only when it carries text, every element child it has is inline,
  // and it is not a flex or grid box; a group is prose only when more than
  // half its members are, so one plain total under four flex p rows (a
  // receipt) does not hide them. The cost: a list built of plain p elements
  // is not judged.
  const PROSE = new Set(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre', 'figcaption']);
  const proseText = (m) => {
    const d = getComputedStyle(m).display;
    return PROSE.has(tag(m)) && !!firstText(m) && kids(m).every((k) => getComputedStyle(k).display === 'inline') && !flexBox(d) && !gridBox(d);
  };
  const prose = (g) => 2 * g.filter(proseText).length > g.length;
  const stackedSet = (el) => repeatedGroups(el).some(([, g]) => !prose(g) && stacks(g) && listLike(g));
  const cellParents = new Set(), cellEls = new Set();
  const cellsOf = (row) => {
    let node = row;
    for (let k = kids(node); k.length === 1 && !ownText(node) && !stackedSet(k[0]); k = kids(node)) node = k[0];
    cellParents.add(node);
    const k = kids(node);
    // A wrapper that holds its own text ("Docs" and an arrow, "Ada", a dot,
    // "Late") is one text cell. A textless leaf after a child's text
    // (<span>Docs</span><svg>) is judged as a column on purpose: a name span
    // followed by a ragged status dot has the same shape. A designed trailing
    // icon is declared data-ruler="off".
    const cells = k.length && !ownText(node) ? k : [node];
    for (const c of cells) cellEls.add(c);
    return cells;
  };
  // A line of words: a word sits wherever the one before it ends, so it is
  // flow, out of the columns and equal-size rules and still read for its
  // baseline. A position is a column when the cell at it or the cell before it
  // is a non-word (not inline-level, no text, a box wider than its own text,
  // or a control) in more than half the rows holding a cell there; position one
  // always is. So a value after a fixed-width label is measured.
  const textWidth = (c) => {
    const r = document.createRange();
    r.selectNodeContents(c);
    return r.getBoundingClientRect().width;
  };
  const widerThanText = (c) => {
    const cs = getComputedStyle(c);
    const inner = c.getBoundingClientRect().width - ['paddingLeft', 'paddingRight', 'borderLeftWidth', 'borderRightWidth']
      .reduce((s, p) => s + (parseFloat(cs[p]) || 0), 0);
    return inner - textWidth(c) > 1;
  };
  // A word is bare: a box with horizontal padding or margin, any border, or
  // taller than one and a half of its lines is a control (a padded, bordered
  // nav link), so a row of them stays a set. Flex and grid items are
  // blockified, never inline-level, so they are never words.
  const control = (c) => {
    const cs = getComputedStyle(c);
    return ['paddingLeft', 'paddingRight', 'marginLeft', 'marginRight'].some((p) => Math.abs(parseFloat(cs[p]) || 0) > 0.5)
      || borderOf(c) > 0.5 || c.getBoundingClientRect().height > 1.5 * lineHeight(c);
  };
  const nonWord = (c) => !inlineLevel(c) || !firstText(c) || widerThanText(c) || control(c);
  const word = (c) => !nonWord(c);
  // Words in text flow are never a set: a space between words is no gap on
  // the scale. A stack of word lines (block-level siblings that each hold only
  // words, two or more, grouped by tag) is a set at any count, so a two-line
  // hero is judged line against line. Tags already judged as a set are left to it.
  const wordLine = (k) => !inlineLevel(k) && !ownText(k) && kids(k).length >= 2 && kids(k).every(word);
  const wordLineGroups = (el, taken) => {
    const groups = new Map();
    for (const k of kids(el)) {
      if (taken.has(tag(k)) || !wordLine(k)) continue;
      if (!groups.has(tag(k))) groups.set(tag(k), []);
      groups.get(tag(k)).push(k);
    }
    return [...groups.entries()].filter(([, g]) => stacks(g));
  };
  const flowEls = new Set();
  const markFlow = (cellLists) => {
    const nw = cellLists.map((cells) => cells.map(nonWord));
    const width = Math.max(...cellLists.map((cells) => cells.length));
    for (let k = 1; k < width; k++) {
      const held = nw.filter((w) => k < w.length);
      if (2 * held.filter((w) => w[k] || w[k - 1]).length > held.length) continue;
      for (const cells of cellLists) if (cells[k]) flowEls.add(cells[k]);
    }
  };
  // The side a set of word lines is set to: its parent's computed text-align,
  // start and end resolved through its direction, justify read as start.
  const alignOf = (el) => {
    const cs = getComputedStyle(el), v = cs.textAlign, rtl = cs.direction === 'rtl';
    if (v.includes('center')) return 'center';
    if (v.includes('left')) return 'left';
    if (v.includes('right')) return 'right';
    return (v === 'end') !== rtl ? 'right' : 'left';
  };
  const textCells = [];
  const cellOf = (c) => {
    const box = boxOf(c);
    const t = firstText(c);
    const m = markOf(c, t);
    const cell = { sig: sig(c), box, baseline: null, fs: null, text: !!t, lines: t ? linesOf(c, box) : null,
                   mark: m ? { sig: sig(m), box: boxOf(m) } : null };
    if (flowEls.has(c)) cell.flow = true;
    if (t) textCells.push([cell, t]);
    return cell;
  };

  // Inside a cell only a horizontal run of inline children is pruned (a flex
  // pill's dot, label and count, all on one band). A block-level grid of cards
  // inside a cell is a set of its own.
  const inlineRun = (el, g) => {
    if (g.every(inlineLevel)) return true;
    const b = g.map(boxOf), lh = lineHeight(el);
    return Math.max(...b.map((x) => x.y)) < Math.min(...b.map((x) => x.y + x.h)) && b.every((x) => x.h <= 1.5 * lh);
  };
  // Does the CSS centre the set's members? The columns rule accepts a centre
  // line only there. Side by side: a flex or grid parent with align-items
  // center, every member align-self center, or every member inline-level with
  // vertical-align middle. Stacked: text-align center over inline-level
  // members, a column flex with align-items center, a grid with justify-items
  // center or every member justify-self center, or every member with auto
  // left and right margins (computedStyleMap keeps the keyword auto, where
  // getComputedStyle resolves it to px). A stacked grid's align-items centres
  // within the row track, never across, so it does not count.
  const centre = (v) => /(^|\s)center$/.test(v || '');
  const autoSides = (m) => {
    const s = m.computedStyleMap();
    return String(s.get('margin-left')) === 'auto' && String(s.get('margin-right')) === 'auto';
  };
  const centred = (el, g) => {
    const cs = getComputedStyle(el), d = cs.display;
    if (stacks(g)) {
      return (cs.textAlign === 'center' && g.every(inlineLevel))
        || (flexBox(d) && cs.flexDirection.startsWith('column') && centre(cs.alignItems))
        || (gridBox(d) && (centre(cs.justifyItems) || g.every((m) => centre(getComputedStyle(m).justifySelf))))
        || g.every(autoSides);
    }
    return ((flexBox(d) || gridBox(d)) && centre(cs.alignItems))
      || g.every((m) => centre(getComputedStyle(m).alignSelf))
      || g.every((m) => inlineLevel(m) && getComputedStyle(m).verticalAlign === 'middle');
  };
  const SECTIONS = new Set(['section', 'article', 'header', 'footer', 'nav', 'main', 'aside']);
  const MOUNTS = new Set(['__next', 'root', 'app', '__nuxt', '__layout', 'svelte']);
  const roots = new Set([document.body]);
  for (let k = kids(document.body), found = false; k.length === 1; k = kids(k[0])) {
    found = found || MOUNTS.has(k[0].id) || tokens(k[0]).includes('root');
    if (!found) break;
    roots.add(k[0]);
  }
  // Only overflow on the page's inline-end side can be scrolled to: a box
  // parked off the start edge (a skip link at left: -9999px) never makes the
  // page scroll sideways, so it is not reported. The page's direction is
  // body's, which inherits the root's unless body sets its own (CSS Writing
  // Modes: body is read before the root element).
  const rtl = getComputedStyle(document.body).direction === 'rtl';
  const sets = [], overflow = [];
  let right = 0, bottom = 0;  // the furthest right and bottom edge of any visible, unclipped box
  const walk = (el, clipped, reported, inCell) => {
    if (shown(el) && !clipped) {
      const b = boxOf(el);
      right = Math.max(right, b.x + b.w);
      bottom = Math.max(bottom, b.y + b.h);
      if (!reported && (rtl ? b.x < -1 : b.x + b.w > vw + 1)) { overflow.push({ path: path(el), box: b }); reported = true; }
    }
    if (tag(el) === 'svg') return;
    const clipsBelow = clipped || CLIPS.has(getComputedStyle(el).overflowX);
    // The in-cell flag passes down only through inline-level children.
    const here = cellEls.has(el) || (inCell && inlineLevel(el));
    if (!cellParents.has(el) && tag(el) !== 'tr') {
      const top = roots.has(el) || tag(el) === 'main';
      // A stacked group is a set only when it is a list, at every depth. A run
      // inside an inline-level parent (an inline-flex pill) is the pill's
      // parts, never a set; the cost is that a dot drifting inside such a pill
      // is not measured.
      const listed = repeatedGroups(el).filter(([t, g]) => !(top && SECTIONS.has(t))
        && (stacks(g) ? !prose(g) && listLike(g) : !inlineLevel(el) && (!here || !inlineRun(el, g)) && !g.every(word)));
      const repeated = [...listed, ...wordLineGroups(el, new Set(listed.map(([t]) => t))).filter(([t]) => !(top && SECTIONS.has(t)))];
      const t = tokens(el);
      const vary = t.includes('vary-height') ? 'height' : t.includes('vary-width') ? 'width' : null;
      for (const [rowTag, rows] of repeated) {
        // A visible sibling outside the set starts a new run.
        const runOf = new Map(), members = new Set(rows);
        let run = 0;
        for (const k of kids(el)) {
          if (members.has(k)) runOf.set(k, run);
          else run++;
        }
        const cellLists = rows.map(cellsOf);
        markFlow(cellLists);
        const set = {
          path: path(el) + (repeated.length > 1 ? ' > ' + rowTag : ''),
          vary,
          rows: rows.map((row, n) => ({ tag: rowTag, sig: sig(row), run: runOf.get(row), box: boxOf(row), border: borderOf(row),
                                        cells: cellLists[n].map(cellOf) })),
        };
        if (centred(el, rows)) set.centred = true;
        const wordLines = cellLists.some((cells) => cells.length > 1) && cellLists.every((cells) => cells.slice(1).every((c) => flowEls.has(c)));
        if (wordLines && alignOf(el) !== 'left') set.align = alignOf(el);
        sets.push(set);
      }
    }
    for (const k of childrenOf(el)) walk(k, clipsBelow, reported, here);
  };
  walk(document.body, false, false, false);
  // Baselines last: every box above is read before any marker touches the DOM.
  baselines(textCells);

  const reach = {};
  if (root.scrollWidth > vw && root.scrollWidth <= vw + 1) reach.right = r2(right);
  if (root.scrollHeight > vh && root.scrollHeight <= vh + 1) reach.bottom = r2(bottom);
  return {
    viewport: { w: vw, h: vh },
    scrollWidth: root.scrollWidth,
    scrollHeight: root.scrollHeight,
    screen: tokens(root).includes('screen') || tokens(document.body).includes('screen'),
    sets,
    overflow,
    off: offSeen.size,
    ...(Object.keys(reach).length ? { reach } : {}),
  };
})()
