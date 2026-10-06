"""Server-rendered charts for the dashboard (docs/DESIGN.md §4): small SVG and HTML, no JavaScript, no external requests.

Shapes are SVG stretched to the plot area; every label is real HTML text so it stays readable on a phone. Every chart has a text
title, values on hover and focus, and a table (or printed values) as the non-visual form. Colour is never the only signal.
"""
from __future__ import annotations

import math
from typing import Callable, Sequence

from markupsafe import Markup, escape

Num = float | int | None


def _esc(x) -> str:
    return str(escape(x))


def _nice_ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, v = [], start
    while v <= hi + step * 0.001:
        ticks.append(round(v, 10))
        v += step
    return ticks


def spark(values: Sequence[Num], *, w: int = 96, h: int = 28, cls: str = "s1", label: str = "", fmt: Callable = lambda v: f"{v:g}") -> Markup:
    """A tiny trend line with its last point marked. `label` names what it shows (read by screen readers)."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return Markup('<span class="muted">—</span>')
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    span = (hi - lo) or 1
    n = len(values) - 1 or 1
    xy = lambda i, v: (2 + (w - 4) * i / n, h - 3 - (h - 6) * (v - lo) / span)
    segs, cur = [], []
    for i, v in enumerate(values):
        if v is None:
            if cur:
                segs.append(cur); cur = []
        else:
            cur.append(xy(i, v))
    if cur:
        segs.append(cur)
    lines = "".join(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in s)}" class="spark-line {cls}"/>' for s in segs if len(s) > 1)
    lx, ly = xy(*pts[-1])
    desc = f"{label}: {fmt(pts[0][1])} → {fmt(pts[-1][1])}" if label else f"{fmt(pts[0][1])} → {fmt(pts[-1][1])}"
    return Markup(f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{_esc(desc)}"><title>{_esc(desc)}</title>'
                  f'{lines}<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2.5" class="spark-dot {cls}"/></svg>')


def line_chart(x_labels: Sequence[str], series: Sequence[dict], *, title: str, y_fmt: Callable = lambda v: f"{v:g}", height: int = 240,
               markers: Sequence[dict] = (), goal: Num = None, goal_label: str = "", table_label: str = "Table", y_zero: bool = False) -> Markup:
    """Weekly trends. series: {"name", "values", "style": "solid"|"dash", "cls": "s1".."s6"}. markers: {"i", "label"} (context on the axis)."""
    vals = [v for s in series for v in s["values"] if v is not None]
    if not vals:
        return Markup('<p class="muted">—</p>')
    lo, hi = (0 if y_zero else min(vals + ([goal] if goal is not None else []))), max(vals + ([goal] if goal is not None else []))
    pad = (hi - lo) * 0.08 or 1
    ticks = _nice_ticks(max(0, lo - pad) if lo >= 0 else lo - pad, hi + pad)
    ylo, yhi = ticks[0], ticks[-1]
    n = max(len(x_labels) - 1, 1)
    X = lambda i: 100 * i / n
    Y = lambda v: 100 - 100 * (v - ylo) / ((yhi - ylo) or 1)
    out = [f'<figure class="chart" role="group" aria-label="{_esc(title)}"><figcaption class="sr-only">{_esc(title)}</figcaption>'
           f'<div class="plot" style="height:{height}px">']
    out.append('<svg viewBox="0 0 100 100" preserveAspectRatio="none" class="plot-svg" aria-hidden="true">')
    for t in ticks:
        out.append(f'<line x1="0" x2="100" y1="{Y(t):.2f}" y2="{Y(t):.2f}" class="grid-line"/>')
    if goal is not None:
        out.append(f'<line x1="0" x2="100" y1="{Y(goal):.2f}" y2="{Y(goal):.2f}" class="goal-line"/>')
    for m in markers:
        out.append(f'<line x1="{X(m["i"]):.2f}" x2="{X(m["i"]):.2f}" y1="0" y2="100" class="marker-line"/>')
    for s in series:
        segs, cur = [], []
        for i, v in enumerate(s["values"]):
            if v is None:
                if cur:
                    segs.append(cur); cur = []
            else:
                cur.append((X(i), Y(v)))
        if cur:
            segs.append(cur)
        for seg in segs:
            if len(seg) > 1:
                out.append(f'<polyline points="{" ".join(f"{x:.2f},{y:.2f}" for x, y in seg)}" class="line {s.get("cls", "s1")} {s.get("style", "solid")}"/>')
    out.append("</svg>")
    for t in ticks:
        out.append(f'<span class="ylab" style="top:{Y(t):.2f}%">{_esc(y_fmt(t))}</span>')
    step = max(1, round(len(x_labels) / 6))
    last_i = len(x_labels) - 1
    for i, lab in enumerate(x_labels):
        if (i % step == 0 and (last_i - i >= step * 0.6 or i == last_i)) or i == last_i:
            out.append(f'<span class="xlab" style="left:{X(i):.2f}%">{_esc(lab)}</span>')
    for k, m in enumerate(markers, 1):
        out.append(f'<span class="flag" style="left:{X(m["i"]):.2f}%" title="{_esc(m["label"])}">{k}</span>')
    if goal is not None and goal_label:
        out.append(f'<span class="goal-lab" style="top:{Y(goal):.2f}%">{_esc(goal_label)}</span>')
    ends = []
    for s in series:                                              # direct labels at the line ends, nudged apart
        last = max((i for i, v in enumerate(s["values"]) if v is not None), default=None)
        if last is not None:
            ends.append([Y(s["values"][last]), s])
    ends.sort(key=lambda e: e[0])
    for k in range(1, len(ends)):
        if ends[k][0] - ends[k - 1][0] < 9:
            ends[k][0] = ends[k - 1][0] + 9
    for y, s in ends:
        out.append(f'<span class="endlab {s.get("cls", "s1")}" style="top:{y:.2f}%">{_esc(s["name"])}</span>')
    for s in series:                                              # hover and focus values
        for i, v in enumerate(s["values"]):
            if v is not None:
                out.append(f'<span class="pt {s.get("cls", "s1")}" style="left:{X(i):.2f}%;top:{Y(v):.2f}%" tabindex="0" '
                           f'title="{_esc(s["name"])}, {_esc(x_labels[i])}: {_esc(y_fmt(v))}"></span>')
    out.append("</div>")
    if markers:
        out.append('<ol class="marker-legend">' + "".join(f'<li value="{k}">{_esc(m["label"])}</li>' for k, m in enumerate(markers, 1)) + "</ol>")
    out.append(f'<details class="chart-table"><summary>{_esc(table_label)}</summary><div class="tablebox"><table><thead><tr><th scope="col" class="l"></th>'
               + "".join(f'<th scope="col">{_esc(s["name"])}</th>' for s in series) + "</tr></thead><tbody>"
               + "".join(f'<tr><td class="l">{_esc(lab)}</td>' + "".join(f'<td>{_esc(y_fmt(s["values"][i])) if s["values"][i] is not None else "—"}</td>' for s in series) + "</tr>"
                         for i, lab in enumerate(x_labels)) + "</tbody></table></div></details></figure>")
    return Markup("".join(out))


def rank_bars(rows: Sequence[dict], *, fmt: Callable = lambda v: f"{v:g}", ref: Num = None, ref_label: str = "", lower_is_better: bool = False) -> Markup:
    """Horizontal bars sorted by value. rows: {"label", "value", "href"?, "cls"?}. `ref` draws the team figure as a marker."""
    rows = [r for r in rows if r["value"] is not None]
    if not rows:
        return Markup('<p class="muted">—</p>')
    rows = sorted(rows, key=lambda r: r["value"], reverse=not lower_is_better)
    top = max(max(r["value"] for r in rows), ref or 0) or 1
    out = ['<div class="rank" role="list">']
    for r in rows:
        w = 100 * r["value"] / top
        name = f'<a href="{_esc(r["href"])}">{_esc(r["label"])}</a>' if r.get("href") else _esc(r["label"])
        mark = f'<i class="ref" style="left:{100 * ref / top:.1f}%" title="{_esc(ref_label)}: {_esc(fmt(ref))}"></i>' if ref else ""
        out.append(f'<div class="rank-row" role="listitem"><span class="rank-name">{name}</span><span class="rank-track"><b class="{_esc(r.get("cls", "s1"))}" '
                   f'style="width:{w:.1f}%"></b>{mark}</span><span class="rank-val">{_esc(fmt(r["value"]))}</span></div>')
    if ref:
        out.append(f'<div class="rank-note"><i class="ref-sample"></i> {_esc(ref_label)}: {_esc(fmt(ref))}</div>')
    out.append("</div>")
    return Markup("".join(out))


def diverging(rows: Sequence[dict], *, fmt: Callable = lambda v: f"{v:+g}", good_when_positive: bool = True) -> Markup:
    """Difference from a reference, centred on zero. rows: {"label", "value", "good"?: bool}. Signed text beside the bar."""
    rows = [r for r in rows if r["value"] is not None]
    if not rows:
        return Markup('<p class="muted">—</p>')
    m = max(abs(r["value"]) for r in rows) or 1
    out = ['<div class="div" role="list">']
    for r in rows:
        v = r["value"]
        good = r.get("good", (v >= 0) == good_when_positive)
        side, w = ("pos" if v >= 0 else "neg"), 50 * abs(v) / m
        out.append(f'<div class="div-row" role="listitem"><span class="rank-name">{_esc(r["label"])}</span><span class="div-track"><b class="{side} {"good" if good else "bad"}" '
                   f'style="width:{w:.1f}%"></b></span><span class="rank-val {"good" if good else "bad"}">{"▲" if v >= 0 else "▼"} {_esc(fmt(v))}</span></div>')
    out.append("</div>")
    return Markup("".join(out))


def stack100(parts: Sequence[dict], *, fmt: Callable = lambda v: f"{v:g}", title: str = "", share: bool = True) -> Markup:
    """One 100% bar with direct labels. parts: {"label", "value", "cls"}. Zero parts are listed in the legend only."""
    total = sum(p["value"] or 0 for p in parts)
    if not total:
        return Markup('<p class="muted">—</p>')
    segs = "".join(f'<span class="seg {_esc(p.get("cls", "s1"))}" style="width:{100 * p["value"] / total:.2f}%" title="{_esc(p["label"])}: {_esc(fmt(p["value"]))} ({100 * p["value"] / total:.0f}%)">'
                   f'{"<em>" + f"{100 * p['value'] / total:.0f}%" + "</em>" if p["value"] / total >= 0.07 else ""}</span>' for p in parts if p["value"])
    legend = "".join(f'<li><i class="sw {_esc(p.get("cls", "s1"))}"></i>{_esc(p["label"])} <b>{_esc(fmt(p["value"]))}</b>{(f' <span class="muted">{100 * (p["value"] or 0) / total:.0f}%</span>' if share else '')}</li>' for p in parts)
    return Markup(f'<div class="stack" role="img" aria-label="{_esc(title)}">{segs}</div><ul class="stack-legend">{legend}</ul>')


def stacked_columns(x_labels: Sequence[str], series: Sequence[dict], *, title: str, height: int = 150, fmt: Callable = lambda v: f"{v:g}") -> Markup:
    """Weekly composition. series: {"name", "values", "cls"}, stacked bottom to top."""
    n = len(x_labels)
    tot = [sum((s["values"][i] or 0) for s in series) for i in range(n)]
    top = max(tot) or 1
    cols = []
    for i in range(n):
        segs = "".join(f'<b class="{_esc(s["cls"])}" style="height:{100 * (s["values"][i] or 0) / top:.1f}%" title="{_esc(s["name"])}, {_esc(x_labels[i])}: {_esc(fmt(s["values"][i] or 0))}"></b>'
                       for s in series)
        cols.append(f'<div class="col" tabindex="0" title="{_esc(x_labels[i])}: {_esc(fmt(tot[i]))}">{segs}</div>')
    step = max(1, round(n / 8))
    axis = "".join(f'<span style="left:{100 * (i + .5) / n:.2f}%">{_esc(x_labels[i])}</span>' for i in range(n) if i % step == 0)
    legend = "".join(f'<li><i class="sw {_esc(s["cls"])}"></i>{_esc(s["name"])}</li>' for s in series)
    return Markup(f'<figure class="chart" role="group" aria-label="{_esc(title)}"><figcaption class="sr-only">{_esc(title)}</figcaption>'
                  f'<div class="cols" style="height:{height}px">{"".join(cols)}</div><div class="cols-axis">{axis}</div><ul class="stack-legend">{legend}</ul></figure>')


def bullet(*, start: Num, current: Num, target: Num, expected: Num = None, fmt: Callable = lambda v: f"{v:g}", lower_is_better: bool = False) -> Markup:
    """Goal progress: a track from start to target, the current value, and today's expected position. Numbers sit beside it."""
    if None in (start, target) or start == target:
        return Markup("")
    lo, hi = sorted((start, target))
    pad = (hi - lo) * 0.15
    a, b = lo - pad, hi + pad
    P = lambda v: max(0.0, min(100.0, 100 * (v - a) / (b - a)))
    if lower_is_better:
        zone = f'<span class="zone" style="left:{P(lo):.1f}%;width:{P(hi) - P(lo):.1f}%"></span>'
    else:
        zone = f'<span class="zone" style="left:{P(lo):.1f}%;width:{P(hi) - P(lo):.1f}%"></span>'
    cur = (f'<span class="cur" style="left:{P(current):.1f}%" title="{_esc(fmt(current))}"></span>' if current is not None else "")
    exp = f'<span class="exp" style="left:{P(expected):.1f}%" title="{_esc(fmt(expected))}"></span>' if expected is not None else ""
    return Markup(f'<div class="bullet" role="img" aria-label="{_esc(fmt(start))} → {_esc(fmt(target))}">{zone}{exp}{cur}'
                  f'<span class="tgt" style="left:{P(target):.1f}%"></span></div>')


def delta_chip(text: str, verdict: str | None) -> Markup:
    """A change as text: ▲/▼ with the signed value. verdict: better | worse | same | None. The word comes from the caller."""
    if not text:
        return Markup('<span class="delta same">—</span>')
    arrow = "▲" if text.lstrip().startswith("+") else "▼" if text.lstrip().startswith(("-", "−")) else ""
    cls = {"better": "good", "worse": "bad"}.get(verdict or "", "same")
    return Markup(f'<span class="delta {cls}">{arrow} {_esc(text.lstrip("+-−"))}</span>')
