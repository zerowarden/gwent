"""Portable HTML reports with accessible SVG charts and no network dependencies."""

from collections.abc import Iterable, Sequence
from html import escape

COLORS = ("#2563eb", "#db2777", "#059669", "#d97706", "#7c3aed", "#0891b2")


def table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    head = "".join(f"<th>{escape(label)}</th>" for label in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>" for row in rows
    )
    return (
        f'<div class="table"><table><thead><tr>{head}</tr></thead>'
        + f"<tbody>{body}</tbody></table></div>"
    )


def percent(value: object, *, difference: bool = False) -> str:
    if not isinstance(value, (int, float)):
        return "not measured"
    return f"{value * 100:+.2f} pp" if difference else f"{value:.2%}"


def chart(
    title: str,
    series: Sequence[tuple[str, Sequence[tuple[float, float]]]],
    *,
    xlabel: str,
    ylabel: str,
) -> str:
    points = [point for _, values in series for point in values]
    if not points:
        return "<p>No completed measurements yet.</p>"
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    dx, dy = xmax - xmin or 1, ymax - ymin or 0.1
    ymin, ymax = ymin - dy * 0.1, ymax + dy * 0.1

    def x(value: float) -> float:
        return 80 + (value - xmin) / dx * 720

    def y(value: float) -> float:
        return 295 - (value - ymin) / (ymax - ymin) * 255

    items = [
        f'<svg viewBox="0 0 850 365" role="img" aria-label="{escape(title, quote=True)}">',
        f"<title>{escape(title)}</title>",
    ]
    for tick in range(6):
        xv = xmin + dx * tick / 5
        yv = ymin + (ymax - ymin) * tick / 5
        items.append(
            f'<path d="M80 {y(yv):.2f}H800" stroke="#dbe3ef"/>'
            + f'<text x="70" y="{y(yv) + 4:.2f}" text-anchor="end">{yv:.3g}</text>'
            + f'<text x="{x(xv):.2f}" y="320" text-anchor="middle">{xv:.3g}</text>'
        )
    legend: list[str] = []
    for index, (label, values) in enumerate(series):
        color = COLORS[index % len(COLORS)]
        coords = " ".join(f"{x(a):.2f},{y(b):.2f}" for a, b in values)
        items.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2"/>')
        for a, b in values:
            tooltip = escape(f"{label}: {xlabel}={a:g}; {ylabel}={b:.5g}")
            items.append(
                f'<circle cx="{x(a):.2f}" cy="{y(b):.2f}" r="4" fill="{color}">'
                + f"<title>{tooltip}</title></circle>"
            )
        legend.append(f'<span style="color:{color}">● {escape(label)}</span>')
    items.extend(
        [
            f'<text x="440" y="350" text-anchor="middle">{escape(xlabel)}</text>',
            f'<text x="80" y="22">{escape(ylabel)}</text>',
            "</svg>",
        ]
    )
    return (
        "<figure>" + "".join(items) + "<figcaption>" + " · ".join(legend) + "</figcaption></figure>"
    )


def document(title: str, introduction: str, sections: Sequence[tuple[str, str]]) -> str:
    navigation = "".join(
        f'<a href="#section-{index}">{escape(name)}</a>' for index, (name, _) in enumerate(sections)
    )
    body = "".join(
        f'<section id="section-{index}"><h2>{escape(name)}</h2>{content}</section>'
        for index, (name, content) in enumerate(sections)
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{escape(title)}</title><style>
:root {{font-family:system-ui,sans-serif;color:#17243a;background:#f3f6fb}}
body {{max-width:1180px;margin:auto;padding:32px}} h1 {{font-size:2.3rem;letter-spacing:-.04em}}
h2 {{font-size:1.4rem}} p,li {{line-height:1.65}} header {{padding:12px 0 24px}}
nav {{display:flex;gap:16px;flex-wrap:wrap;margin:20px 0}} a {{color:#1d4ed8}}
section {{background:white;padding:24px;margin:20px 0;border:1px solid #dbe3ef;border-radius:12px}}
.table {{overflow-x:auto}} table {{border-collapse:collapse;width:100%;font-size:.9rem}}
th,td {{padding:10px;text-align:left;border-bottom:1px solid #e2e8f0;vertical-align:top}}
th {{background:#f8fafc}} td {{overflow-wrap:anywhere}} figure {{margin:16px 0}}
svg {{width:100%;max-height:410px}} svg text {{font:12px system-ui;fill:#475569}}
figcaption {{font-size:.85rem}} pre {{white-space:pre-wrap;overflow-wrap:anywhere}}
summary {{cursor:pointer;padding:8px 0}} .note {{background:#eef4ff;padding:12px;border-radius:8px}}
@media print {{body {{padding:0}} section {{break-inside:avoid}} nav {{display:none}}}}
</style></head><body><header><small>GWENT · EVALUATION</small><h1>{escape(title)}</h1>
<p>{escape(introduction)}</p><nav>{navigation}</nav></header>{body}
<footer><p>Generated from recorded evidence. Charts are descriptive;
promotion requires the frozen evaluation gates.</p></footer>
</body></html>"""
