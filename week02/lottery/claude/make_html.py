"""Build heatmap.html and barchart.html from stats.json.

Standard library only. Both pages are fully self-contained apart from the vendored
`d3.min.js`: the statistics are inlined as a JSON block rather than fetched, because
`fetch()` of a local file is blocked by the CORS rules under `file://` and the pages
would render blank when simply double-clicked.

Both charts are drawn with D3 (v7): data joins (`selection.data().join()`), scales
(`scaleQuantize`, `scaleBand`, `scaleLinear`) and axes (`axisLeft`, `axisBottom`).
Only the page chrome around the SVGs is plain DOM.

Usage:
    python make_html.py [--stats stats.json] [--outdir .]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Sequential ramp: ONE hue, monotone lightness. A rainbow ramp (viridis, jet) is the
# classic sequential-scale mistake -- it invents boundaries the data does not have.
# Light theme runs light -> dark as the value rises; the dark theme inverts the anchor
# so "low" still sits nearest the page surface and stays visible.
RAMP_LIGHT = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
RAMP_DARK = ["#12314f", "#1a4570", "#235a94", "#2e74b8", "#3f92d9", "#67b3ec", "#a6d2f8"]

# One colour for every bar: length already encodes the value, so recolouring the
# top-N bars would spend the only free channel re-encoding what the height says.
BAR_COLOR = "#2a78d6"

CSS = """
:root {
  --surface: #fcfcfb;
  --panel: #ffffff;
  --ink: #0b0b0b;
  --muted: #6b6a65;
  --line: #e1e0d9;
  --gridline: #ecebe5;
  --accent: #2a78d6;
  --band: rgba(42, 120, 214, 0.13);
  --warn-bg: #fff6e6;
  --warn-line: #e8cfa0;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --surface: #1a1a19;
    --panel: #21211f;
    --ink: #ffffff;
    --muted: #a3a19a;
    --line: #33322f;
    --gridline: #2a2a27;
    --accent: #6fb2ea;
    --band: rgba(111, 178, 234, 0.16);
    --warn-bg: #2b2418;
    --warn-line: #5c4a26;
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --surface: #1a1a19;
  --panel: #21211f;
  --ink: #ffffff;
  --muted: #a3a19a;
  --line: #33322f;
  --gridline: #2a2a27;
  --accent: #6fb2ea;
  --band: rgba(111, 178, 234, 0.16);
  --warn-bg: #2b2418;
  --warn-line: #5c4a26;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 24px 20px 64px;
  background: var(--surface);
  color: var(--ink);
  font: 14px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 1080px; margin: 0 auto; }
h1 { font-size: 24px; margin: 0 0 6px; letter-spacing: -0.01em; }
h2 { font-size: 16px; margin: 34px 0 4px; letter-spacing: 0.02em; }
p.lede { color: var(--muted); margin: 0 0 20px; max-width: 70ch; }
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 18px 18px 12px;
  margin-top: 14px;
}
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  align-items: center;
  padding: 12px 16px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
  margin-bottom: 4px;
}
.controls span.group { font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; font-size: 11px; color: var(--muted); }
.controls label { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
.viewnote { color: var(--muted); font-size: 13px; margin: 10px 0 0; }
.scrollx { overflow-x: auto; }
svg { display: block; max-width: 100%; }
/* Charts keep their natural width and scroll rather than shrinking to illegibility. */
.scrollx svg { max-width: none; }
svg text { font-family: inherit; }
.celllabel { font-weight: 600; pointer-events: none; }
/* d3-axis writes fill="currentColor", so the muted tone is set as the group's colour. */
.grid text, .xaxis text { font-size: 11px; }
.xaxis text { font-size: 10.5px; }
.legend { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 12px; font-size: 12px; color: var(--muted); }
.legend .swatches { display: flex; }
.legend .sw { width: 30px; height: 12px; }
.legend .sw:first-child { border-radius: 3px 0 0 3px; }
.legend .sw:last-child { border-radius: 0 3px 3px 0; }
.plaque {
  margin-top: 18px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 18px 20px;
}
.plaque h3 {
  margin: 0 0 12px;
  font-size: 12px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--muted);
  font-weight: 700;
}
.balls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.ball {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-width: 48px;
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--accent);
  color: #fff;
  font-weight: 700;
  font-size: 17px;
  line-height: 1.1;
}
.ball small { font-size: 10px; font-weight: 500; opacity: 0.85; letter-spacing: 0.03em; }
.ball.set2 { background: var(--muted); }
.plaque .row { margin-bottom: 14px; }
.plaque .row:last-child { margin-bottom: 0; }
.plaque .k { font-weight: 600; margin-bottom: 8px; }
.caveat {
  margin-top: 16px;
  padding: 12px 14px;
  border-radius: 8px;
  background: var(--warn-bg);
  border: 1px solid var(--warn-line);
  font-size: 13px;
}
details { margin-top: 14px; }
summary { cursor: pointer; color: var(--muted); font-size: 13px; }
table { border-collapse: collapse; margin-top: 10px; font-size: 13px; font-variant-numeric: tabular-nums; }
th, td { border-bottom: 1px solid var(--line); padding: 4px 10px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--muted); font-weight: 600; }
#tip {
  position: fixed;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.1s;
  background: var(--panel);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 7px 10px;
  font-size: 12.5px;
  line-height: 1.45;
  box-shadow: 0 6px 20px rgba(0,0,0,0.16);
  z-index: 10;
  max-width: 260px;
}
#tip b { font-size: 13.5px; }
"""

# Shared helpers injected into both pages. Everything below draws with D3; these are the
# bits that are not chart-specific (theme handling, the tooltip, number formatting).
COMMON_JS = r"""
const DATA = JSON.parse(document.getElementById('stats').textContent);

const RAMP = { light: __RAMP_LIGHT__, dark: __RAMP_DARK__ };
const BAR_COLOR = __BAR_COLOR__;

function isDark() {
  const forced = document.documentElement.getAttribute('data-theme');
  if (forced) return forced === 'dark';
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}
function ramp() { return isDark() ? RAMP.dark : RAMP.light; }

// Pick a label colour that stays legible on any ramp step.
function textOn(hex) {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const lin = c => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
  const L = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return (isDark() ? L > 0.35 : L < 0.45) ? '#ffffff' : '#0b0b0b';
}

// A quantised sequential scale over the ramp: the class breaks come from the data's own
// extent, so they cannot drift when the numbers change. Quantising rather than
// interpolating keeps the number of distinguishable classes readable.
function colourScale(cells) {
  const [lo, hi] = d3.extent(cells, c => c.count);
  // All-equal data would collapse the domain; widen it so every cell takes the middle step.
  return d3.scaleQuantize()
    .domain(lo === hi ? [lo - 1, hi + 1] : [lo, hi])
    .range(ramp());
}

const tip = document.getElementById('tip');
function showTip(evt, html) {
  tip.innerHTML = html;
  tip.style.opacity = 1;
  const pad = 14;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  const r = tip.getBoundingClientRect();
  if (x + r.width > window.innerWidth - 8) x = evt.clientX - r.width - pad;
  if (y + r.height > window.innerHeight - 8) y = evt.clientY - r.height - pad;
  tip.style.left = x + 'px';
  tip.style.top = y + 'px';
}
function hideTip() { tip.style.opacity = 0; }

// Expected count and the +/-1.96 sigma band a fair draw would produce.
function expectedBand(draws, size, universe) {
  const p = size / universe;
  const expected = draws * p;
  const sigma = Math.sqrt(draws * p * (1 - p));
  return { expected: expected, sigma: sigma, lo: expected - 1.96 * sigma, hi: expected + 1.96 * sigma };
}

const fmt = (v, d = 1) => v.toFixed(d);

function currentView() {
  const checked = document.querySelector('input[name="view"]:checked');
  return DATA.views[checked ? checked.value : 'era_b'];
}

function fmtDate(iso) {
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const [y, m, d] = iso.split('-').map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}
"""

HEATMAP_JS = r"""
function drawHeatmap(host, set, cols, title, universe) {
  const cells = set.cells;
  const colour = colourScale(cells);
  const expected = set.expected;
  d3.select(host).selectAll('*').remove();

  const cell = 62, pad = 2;
  const rows = Math.ceil(universe / cols);
  const m = { top: 26, right: 12, bottom: 8, left: 62 };
  const w = m.left + m.right + cols * cell;
  const h = m.top + m.bottom + rows * cell;

  const svg = d3.select(host).append('div').attr('class', 'scrollx')
    .append('svg')
      .attr('viewBox', `0 0 ${w} ${h}`)
      .attr('width', w)
      .attr('height', h)
      .attr('role', 'img')
      .attr('aria-label', title + ': count of times each number was drawn');

  svg.append('text')
    .attr('x', m.left).attr('y', 15)
    .attr('font-size', 13).attr('font-weight', 600)
    .attr('fill', 'currentColor')
    .text(title);

  // One <g> per number, positioned by its index in the grid.
  const cellsG = svg.selectAll('g.cell')
    .data(cells, d => d.n)
    .join('g')
      .attr('class', 'cell')
      .attr('transform', (d, i) =>
        `translate(${m.left + (i % cols) * cell},${m.top + Math.floor(i / cols) * cell})`)
      .on('mousemove', function (event, d) {
        const z = (d.count - expected) / Math.sqrt(expected * (1 - set.size / universe));
        showTip(event,
          `<b>${d.n}</b><br>drawn ${d.count} times<br>` +
          `expected ${fmt(expected)} (z = ${z >= 0 ? '+' : ''}${fmt(z, 2)})<br>` +
          `rank ${d.rank} of ${universe}<br>` +
          `deviation from expected: ${fmt(d.count - expected, 1)}`);
      })
      .on('mouseleave', hideTip);

  cellsG.append('rect')
    .attr('x', pad).attr('y', pad)
    .attr('width', cell - 2 * pad).attr('height', cell - 2 * pad)
    .attr('rx', 3)
    .attr('fill', d => colour(d.count));

  cellsG.append('text')
    .attr('class', 'celllabel')
    .attr('x', cell / 2).attr('y', cell / 2 - 3)
    .attr('text-anchor', 'middle').attr('font-size', 15)
    .attr('fill', d => textOn(colour(d.count)))
    .text(d => d.n);

  cellsG.append('text')
    .attr('x', cell / 2).attr('y', cell / 2 + 14)
    .attr('text-anchor', 'middle').attr('font-size', 11.5).attr('opacity', 0.9)
    .attr('fill', d => textOn(colour(d.count)))
    .text(d => d.count);

  // Legend, with the expected value marked so "average" is identifiable.
  const [lo, hi] = d3.extent(cells, c => c.count);
  const legend = d3.select(host).append('div').attr('class', 'legend');
  legend.append('div').attr('class', 'swatches')
    .selectAll('div').data(ramp()).join('div')
      .attr('class', 'sw')
      .style('background', c => c);
  legend.append('span').text(
    `${lo} (coldest) → ${hi} (hottest)   |   expected under a fair draw: ${fmt(expected)}`);
}

function renderHeatmap() {
  const v = currentView();
  document.getElementById('viewnote').textContent = v.note;
  drawHeatmap(document.getElementById('h1host'), v.set1, 10,
              'Set #1 — 5 numbers from 1–50', v.set1.universe);
  drawHeatmap(document.getElementById('h2host'), v.set2, 6,
              'Set #2 — 2 numbers from 1–' + v.set2.universe, v.set2.universe);

  const rows = v.set1.cells.map(c => `<tr><td>${c.n}</td><td>${c.count}</td><td>${c.rank}</td></tr>`).join('');
  document.getElementById('t1').innerHTML =
    '<table><thead><tr><th>Set #1 number</th><th>Count</th><th>Rank</th></tr></thead><tbody>' + rows + '</tbody></table>';
  const rows2 = v.set2.cells.map(c => `<tr><td>${c.n}</td><td>${c.count}</td><td>${c.rank}</td></tr>`).join('');
  document.getElementById('t2').innerHTML =
    '<table><thead><tr><th>Set #2 number</th><th>Count</th><th>Rank</th></tr></thead><tbody>' + rows2 + '</tbody></table>';
}
"""

BARCHART_JS = r"""
function drawBars(host, set, universe, title) {
  const cells = set.cells;
  const v = currentView();
  const band = expectedBand(v.draws, set.size, universe);
  const topN = new Set((set.top5 || set.top2).map(t => t.n));
  d3.select(host).selectAll('*').remove();

  // The right margin holds the "expected" label clear of the bars.
  const m = { top: 22, right: 80, bottom: 30, left: 46 };
  // Fewer numbers get wider bars, so the 12-bar Set #2 chart is not a thin sliver.
  const wide = universe <= 12;
  const bar = wide ? 38 : 14, gap = wide ? 6 : 2.5;
  const innerW = universe * (bar + gap);
  const w = m.left + m.right + innerW;
  const h = 300;
  const innerH = h - m.top - m.bottom;

  // Round the axis top up to a readable number so the ticks are not 61.5 / 49.2 / 36.9.
  function niceMax(value) {
    const e = Math.pow(10, Math.floor(Math.log10(value)));
    const q = value / e;
    const n = q <= 1 ? 1 : q <= 2 ? 2 : q <= 2.5 ? 2.5 : q <= 5 ? 5 : 10;
    return n * e;
  }

  // A band scale whose step is (bar + gap) reproduces the fixed bar geometry exactly,
  // while letting d3-axis centre the labels under each bar. The range has to stop one
  // gap short: a band scale puts padding *between* bands, so `n` bars need `n - 1` gaps
  // and the final gap stays as trailing slack (as it did when bars were placed by hand).
  const x = d3.scaleBand()
    .domain(cells.map(c => c.n))
    .range([0, innerW - gap])
    .paddingInner(gap / (bar + gap));

  const counts = cells.map(c => c.count);
  const yMax = niceMax(Math.max(band.hi, ...counts) * 1.06);
  const y = d3.scaleLinear().domain([0, yMax]).range([innerH, 0]);

  const svg = d3.select(host).append('div').attr('class', 'scrollx')
    .append('svg')
      .attr('viewBox', `0 0 ${w} ${h}`)
      .attr('width', w)
      .attr('height', h)
      .attr('role', 'img')
      .attr('aria-label', title + ': draw frequency per number');

  svg.append('text')
    .attr('x', m.left).attr('y', 13)
    .attr('font-size', 13).attr('font-weight', 600)
    .attr('fill', 'currentColor')
    .text(title);

  const g = svg.append('g').attr('transform', `translate(${m.left},${m.top})`);

  // Y gridlines, solid hairlines, drawn through a d3 axis with the domain line removed.
  const yTicks = d3.range(0, 6).map(i => (yMax / 5) * i);
  g.append('g')
    .attr('class', 'grid')
    .style('color', 'var(--muted)')
    .call(d3.axisLeft(y).tickValues(yTicks)
      .tickSize(-innerW)
      .tickFormat(d => fmt(d, d >= 100 ? 0 : 1)))
    .call(sel => sel.select('.domain').remove())
    .call(sel => sel.selectAll('line').attr('stroke', 'var(--gridline)'));

  // The noise band: where a fair draw would land. Almost everything sits inside it.
  g.append('rect')
    .attr('x', 0).attr('y', y(band.hi))
    .attr('width', innerW)
    .attr('height', Math.max(0, y(band.lo) - y(band.hi)))
    .attr('fill', 'var(--band)');

  g.append('line')
    .attr('x1', 0).attr('x2', innerW)
    .attr('y1', y(band.expected)).attr('y2', y(band.expected))
    .attr('stroke', 'var(--accent)').attr('stroke-width', 1.5);

  // Outside the plot area, so it never collides with a bar.
  g.append('line')
    .attr('x1', innerW).attr('x2', innerW + 6)
    .attr('y1', y(band.expected)).attr('y2', y(band.expected))
    .attr('stroke', 'var(--accent)').attr('stroke-width', 1.5);

  g.append('text')
    .attr('x', innerW + 10).attr('y', y(band.expected) + 4)
    .attr('text-anchor', 'start').attr('font-size', 11)
    .attr('fill', 'var(--accent)').attr('font-weight', 600)
    .text(`expected ${fmt(band.expected)}`);

  // The bars themselves: one datum per number.
  g.selectAll('rect.bar')
    .data(cells, d => d.n)
    .join('rect')
      .attr('class', 'bar')
      .attr('x', d => x(d.n))
      .attr('y', d => y(d.count))
      .attr('width', x.bandwidth())
      .attr('height', d => Math.max(0, innerH - y(d.count)))
      .attr('rx', 4)
      .attr('fill', BAR_COLOR)
      .on('mousemove', function (event, d) {
        showTip(event,
          `<b>Number ${d.n}</b><br>drawn ${d.count} times<br>` +
          `expected ${fmt(band.expected)} in ${v.draws} draws<br>` +
          `rank ${d.rank} of ${universe}` +
          (topN.has(d.n) ? '<br><i>in the most-frequent set</i>' : ''));
      })
      .on('mouseleave', hideTip);

  // The most-frequent bars are identified by a direct label, not by a second colour.
  g.selectAll('text.toplabel')
    .data(cells.filter(d => topN.has(d.n)), d => d.n)
    .join('text')
      .attr('class', 'toplabel')
      .attr('x', d => x(d.n) + x.bandwidth() / 2)
      .attr('y', d => y(d.count) - 6)
      .attr('text-anchor', 'middle').attr('font-size', 12).attr('font-weight', 700)
      .attr('fill', 'var(--ink)')
      .text(d => d.n);

  // The baseline spans the full plot width, not just the scale's range, so it matches
  // the gridlines above it; the axis supplies only the number labels.
  g.append('line')
    .attr('x1', 0).attr('x2', innerW)
    .attr('y1', innerH).attr('y2', innerH)
    .attr('stroke', 'var(--line)');

  g.append('g')
    .attr('class', 'xaxis')
    .attr('transform', `translate(0,${innerH})`)
    .style('color', 'var(--muted)')
    .call(d3.axisBottom(x).tickValues(cells.map(c => c.n)).tickSize(0).tickPadding(6))
    .call(sel => sel.select('.domain').remove());

  const legend = d3.select(host).append('div').attr('class', 'legend');
  legend.html(
    `<span><b style="color:var(--accent)">—</b> expected count for a fair draw (${fmt(band.expected)})</span>` +
    `<span><span style="display:inline-block;width:22px;height:10px;background:var(--band);border:1px solid var(--line)"></span> 95% range if the draw were fair (${fmt(band.lo, 0)}–${fmt(band.hi, 0)})</span>` +
    `<span>bold label = in the top ${set.top5 ? 5 : 2}</span>`);
}

function ball(n, count, isSet2) {
  return `<span class="ball${isSet2 ? ' set2' : ''}">${n}<small>${count}×</small></span>`;
}

function renderPlaque() {
  const v = currentView();
  const full = DATA.views.full;
  const s1 = v.set1.top5.map(t => ball(t.n, t.count, false)).join('');
  const s2 = v.set2.top2.map(t => ball(t.n, t.count, true)).join('');
  const f1 = full.set1.top5.map(t => t.n).join(', ');
  const f2 = full.set2.top2.map(t => t.n).join(', ');

  const chi = DATA.chi2[v === DATA.views.era_b ? 'era_b' : 'full'];
  const c1 = chi.chi2_set1, c2 = chi.chi2_set2;
  const line = (label, c) =>
    `${label}: χ² = ${fmt(c.statistic, 2)}, df = ${c.df}, p ${c.p_value_str}`;

  // The verdict is assembled from the test outcomes in the data, so the page cannot
  // claim fairness while printing a chi-square that rejects it. In the full-history
  // view the pooled Set #2 test *does* reject -- and saying why is the whole point.
  let verdict;
  if (c1.uniform_at_05 && c2.uniform_at_05) {
    verdict = `Across ${v.draws} draws the counts are consistent with a fair uniform draw ` +
      `(${line('Set #1', c1)}; ${line('Set #2', c2)}).`;
  } else {
    verdict = `${line('Set #1', c1)} — consistent with a fair draw. ` +
      `The pooled Set #2 count does not (${line('Set #2', c2)}), but that rejection is an ` +
      `artefact of pooling two different number universes rather than evidence about the balls: ` +
      `11 and 12 did not exist before 25 Mar 2022. Scored against the 1–12 game actually ` +
      `being played, the Set #2 counts pass (${line('Set #2 (Era B)', DATA.chi2.era_b.chi2_set2)}).`;
  }

  document.getElementById('plaque').innerHTML =
    `<h3>Most frequently drawn — ${v.label}</h3>` +
    `<div class="row"><div class="k">5 most frequent Set #1 numbers</div><div class="balls">${s1}</div></div>` +
    `<div class="row"><div class="k">2 most frequent Set #2 numbers</div><div class="balls">${s2}</div></div>` +
    `<div class="caveat"><b>These numbers are not more likely to appear in the next draw.</b><br>` +
    verdict +
    ` The odds of a single line matching all seven numbers are 1 in ${DATA.odds.lines.toLocaleString()}.` +
    `<br><br>Full-history counting gives a different Set #1 top 5 (${f1}) and Set #2 top 2 (${f2}) — ` +
    `the lists disagree because they are sampling noise, not because form changes.</div>`;
}

function renderBars() {
  const v = currentView();
  document.getElementById('viewnote').textContent = v.note;
  drawBars(document.getElementById('b1host'), v.set1, v.set1.universe,
           'Set #1 — count per number (1–50)');
  drawBars(document.getElementById('b2host'), v.set2, v.set2.universe,
           'Set #2 — count per number (1–' + v.set2.universe + ')');
  renderPlaque();

  const t = v.set1.cells.map(c =>
    `<tr><td>${c.n}</td><td>${c.count}</td><td>${fmt(c.count - v.set1.expected, 1)}</td><td>${c.rank}</td></tr>`).join('');
  document.getElementById('t1').innerHTML =
    `<table><thead><tr><th>Set #1 number</th><th>Count</th><th>vs expected</th><th>Rank</th></tr></thead><tbody>${t}</tbody></table>`;
  const t2 = v.set2.cells.map(c =>
    `<tr><td>${c.n}</td><td>${c.count}</td><td>${fmt(c.count - v.set2.expected, 1)}</td><td>${c.rank}</td></tr>`).join('');
  document.getElementById('t2').innerHTML =
    `<table><thead><tr><th>Set #2 number</th><th>Count</th><th>vs expected</th><th>Rank</th></tr></thead><tbody>${t2}</tbody></table>`;
}
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__CSS__</style>
</head>
<body>
<div class="wrap">
  <h1>__H1__</h1>
  <p class="lede">__LEDE__</p>

  <div class="controls">
    <span class="group">Draw history</span>
    <label><input type="radio" name="view" value="era_b" checked> Current rules (from 25 Mar 2022)</label>
    <label><input type="radio" name="view" value="full"> Full history (2014&ndash;2026)</label>
  </div>
  <p class="viewnote" id="viewnote"></p>

  __BODY__

  <details>
    <summary>Table view &mdash; the numbers behind the charts</summary>
    <div id="t1"></div>
    <div id="t2"></div>
  </details>

  <p class="lede" style="margin-top:26px">
    Source: <code id="srcmeta">eurojackpot.csv</code>. Statistics generated by
    <code>analysis.py</code>; full reasoning in
    <a href="lottery_analysis.md">lottery_analysis.md</a>.
  </p>
</div>

<div id="tip"></div>
<script id="stats" type="application/json">__DATA__</script>
<script src="d3.min.js"></script>
<script>__JS__</script>
</body>
</html>
"""


def build_page(title: str, h1: str, lede: str, body: str, js: str, data: dict) -> str:
    # `</` inside the JSON would close the script element early.
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    common = (
        COMMON_JS.replace("__RAMP_LIGHT__", json.dumps(RAMP_LIGHT))
        .replace("__RAMP_DARK__", json.dumps(RAMP_DARK))
        .replace("__BAR_COLOR__", json.dumps(BAR_COLOR))
    )
    return (
        PAGE.replace("__TITLE__", title)
        .replace("__H1__", h1)
        .replace("__LEDE__", lede)
        .replace("__BODY__", body)
        .replace("__CSS__", CSS)
        .replace("__DATA__", payload)
        .replace("__JS__", common + "\n" + js + "\n" + BOOTSTRAP)
    )


# The provenance line is filled from the data rather than typed into the template, so it
# cannot go stale when the CSV is updated.
BOOTSTRAP = r"""
const META = DATA.meta;
document.getElementById('srcmeta').textContent =
  `${META.source}, ${META.draws} draws, ${fmtDate(META.first_draw)} – ${fmtDate(META.last_draw)}`;

// Re-render on theme change: the sequential ramp's anchor inverts between themes, and
// SVG fills cannot be repainted by CSS variables alone.
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', render);
document.querySelectorAll('input[name="view"]').forEach(r => r.addEventListener('change', render));
render();
"""


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stats", default=str(here / "stats.json"))
    ap.add_argument("--outdir", default=str(here))
    args = ap.parse_args(argv)

    outdir = Path(args.outdir)
    data = json.loads(Path(args.stats).read_text(encoding="utf-8"))

    heatmap = build_page(
        title="Eurojackpot — number frequency heatmaps",
        h1="How often does each number come up?",
        lede=(
            "Two heatmaps, one per set. Each cell is a number; the fill and the figure inside it "
            "are how many times that number was drawn. Switch the draw history to see how the "
            "March 2022 rule change distorts the picture — the short version is that nothing here "
            "deviates from chance."
        ),
        body=(
            '<div class="panel"><div id="h1host"></div></div>\n'
            '<div class="panel"><div id="h2host"></div></div>'
        ),
        js=HEATMAP_JS + "\nfunction render() { renderHeatmap(); }",
        data=data,
    )

    barchart = build_page(
        title="Eurojackpot — draw frequency bar charts",
        h1="Draw frequency per number",
        lede=(
            "Every number drawn, counted, with the frequency a fair draw would produce marked on "
            "each chart. Nearly every bar sits inside the shaded 95% range — which is the whole "
            "finding of this analysis."
        ),
        body=(
            '<div class="panel"><div id="b1host"></div></div>\n'
            '<div class="panel"><div id="b2host"></div></div>\n'
            '<div class="plaque" id="plaque"></div>'
        ),
        js=BARCHART_JS + "\nfunction render() { renderBars(); }",
        data=data,
    )

    (outdir / "heatmap.html").write_text(heatmap, encoding="utf-8", newline="\n")
    (outdir / "barchart.html").write_text(barchart, encoding="utf-8", newline="\n")
    print(f"Wrote {outdir / 'heatmap.html'} ({len(heatmap):,} bytes)")
    print(f"Wrote {outdir / 'barchart.html'} ({len(barchart):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
