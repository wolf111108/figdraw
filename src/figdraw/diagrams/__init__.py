"""Theme-aware SVG renderer; layout geometry is expressed in physical points."""

import json
from xml.etree.ElementTree import Element, SubElement, tostring

from matplotlib.font_manager import FontProperties
from matplotlib.path import Path as MplPath
from matplotlib.textpath import TextPath, TextToPath

from figdraw.diagrams.layout import compute_layout
from figdraw.errors import FigdrawError
from figdraw.themes import PT_PER_MM


def svg_figure(ctx, saved, outline=False):
    spec, t, g = ctx.spec, ctx.theme, saved["geometry"]
    w, h = spec.size.width_mm * PT_PER_MM, spec.size.height_mm * PT_PER_MM
    title_h = t.typography.title_pt * 2.5 if spec.labels.title else 0
    if g["width"] > w or g["height"] + title_h > h:
        raise FigdrawError(
            f"diagram needs at least {g['width'] / PT_PER_MM:.1f} × {(g['height'] + title_h) / PT_PER_MM:.1f} mm; enlarge size (no automatic shrink)"
        )
    dx, dy = (w - g["width"]) / 2, (h - title_h - g["height"]) / 2 + title_h
    root = Element(
        "svg",
        {
            "xmlns": "http://www.w3.org/2000/svg",
            "width": f"{spec.size.width_mm}mm",
            "height": f"{spec.size.height_mm}mm",
            "viewBox": f"0 0 {w} {h}",
        },
    )
    SubElement(root, "title").text = spec.labels.title or spec.id

    def el(tag, **attrs):
        return SubElement(root, tag, {k.replace("_", "-"): str(v) for k, v in attrs.items()})

    el("rect", x=0, y=0, width=w, height=h, fill=t.background)

    def text(label, x, y, size=None, anchor="middle", stable_id=None, global_coords=False):
        size = size or t.typography.size_pt
        if not global_coords:
            x, y = x + dx, y + dy
        if stable_id in spec.overrides.labels:
            offset = spec.overrides.labels[stable_id]
            x, y = x + offset.dx_pt, y + offset.dy_pt
        prop = FontProperties(fname=ctx.font["file"], size=size)
        lines = label.split("\n")
        for i, line in enumerate(lines):
            width = TextToPath().get_text_width_height_descent(line, prop, False)[0]
            left = x - width / 2 if anchor == "middle" else x
            baseline = y + (i - (len(lines) - 1) / 2) * size * 1.35 + size * 0.35
            if left < 0 or left + width > w or baseline - size < 0 or baseline + size * 0.25 > h:
                raise FigdrawError(
                    f"diagram label {line!r} exceeds canvas; enlarge size or adjust label offset"
                )
            if outline and line.strip():
                path = TextPath((0, 0), line, prop=prop, size=size, usetex=False)
                commands = []
                for vertices, code in path.iter_segments(curves=True, simplify=False):
                    pairs = [
                        (left + vertices[j], baseline - vertices[j + 1])
                        for j in range(0, len(vertices), 2)
                    ]
                    command = {
                        MplPath.MOVETO: "M",
                        MplPath.LINETO: "L",
                        MplPath.CURVE3: "Q",
                        MplPath.CURVE4: "C",
                        MplPath.CLOSEPOLY: "Z",
                    }[code]
                    commands.append(
                        command
                        + (" ".join(f"{a:.5f},{b:.5f}" for a, b in pairs) if command != "Z" else "")
                    )
                el("path", d=" ".join(commands), fill=t.foreground)
            else:
                el(
                    "text",
                    x=x,
                    y=baseline,
                    text_anchor=anchor,
                    font_family=ctx.font["family"],
                    font_size=size,
                    fill=t.foreground,
                ).text = line

    if spec.labels.title:
        text(
            spec.labels.title,
            w / 2,
            t.typography.title_pt,
            t.typography.title_pt,
            global_coords=True,
        )
    # Paint parent backgrounds before their children, independently of input order.
    for group in sorted(
        spec.graph.groups, key=lambda x: -g["groups"][x.id]["width"] * g["groups"][x.id]["height"]
    ):
        n = g["groups"][group.id]
        el(
            "rect",
            id=group.id,
            x=n["x"] + dx,
            y=n["y"] + dy,
            width=n["width"],
            height=n["height"],
            rx=t.radius_pt,
            fill=t.group_fill,
            stroke=t.grid_color,
            stroke_width=t.line_pt,
        )
        if n["labels"]:
            label = n["labels"][0]
            text(
                group.label,
                label["x"],
                label["y"] + label["height"] / 2,
                anchor="start",
                stable_id=group.id,
            )
    for edge in spec.graph.edges:
        entry = g["edges"][edge.id]
        color = t.control_color if edge.role == "control" else t.foreground
        points = entry["points"]
        if any(not 0 <= p["x"] + dx <= w or not 0 <= p["y"] + dy <= h for p in points):
            raise FigdrawError(f"edge {edge.id}: route exceeds canvas")
        el(
            "polyline",
            id=edge.id,
            points=" ".join(f"{p['x'] + dx},{p['y'] + dy}" for p in points),
            fill="none",
            stroke=color,
            stroke_width=t.data_line_pt if edge.role == "data" else t.line_pt,
            stroke_dasharray="4 3" if edge.role == "control" else "none",
        )
        end = points[-1]
        previous = next((p for p in reversed(points[:-1]) if p != end), points[0])
        vx, vy = end["x"] - previous["x"], end["y"] - previous["y"]
        length = (vx * vx + vy * vy) ** 0.5
        if length:
            ux, uy = vx / length, vy / length
            x, y = end["x"] + dx, end["y"] + dy
            el(
                "polygon",
                points=f"{x},{y} {x - 5 * ux + 2 * uy},{y - 5 * uy - 2 * ux} {x - 5 * ux - 2 * uy},{y - 5 * uy + 2 * ux}",
                fill=color,
            )
        for label in entry["labels"]:
            x, y = label["x"], label["y"]
            offset = spec.overrides.labels.get(edge.id)
            ox, oy = (offset.dx_pt, offset.dy_pt) if offset else (0, 0)
            el(
                "rect",
                x=x + dx + ox - 2,
                y=y + dy + oy - 1,
                width=label["width"] + 4,
                height=label["height"] + 2,
                fill=t.background,
            )
            text(edge.label, x + label["width"] / 2, y + label["height"] / 2, stable_id=edge.id)
    for node in spec.graph.nodes:
        n = g["nodes"][node.id]
        x, y, nw, nh = n["x"] + dx, n["y"] + dy, n["width"], n["height"]
        if min(x, y) < 0 or x + nw > w or y + nh > h:
            raise FigdrawError(f"node {node.id}: outside canvas")
        attrs = {
            "id": node.id,
            "fill": t.node_fill,
            "stroke": t.foreground,
            "stroke_width": t.line_pt,
        }
        if node.component == "junction":
            el("circle", cx=x + nw / 2, cy=y + nh / 2, r=nw / 2, fill=t.foreground)
        elif node.component == "decision":
            el(
                "polygon",
                points=f"{x + nw / 2},{y} {x + nw},{y + nh / 2} {x + nw / 2},{y + nh} {x},{y + nh / 2}",
                **attrs,
            )
        elif node.component == "mux":
            el(
                "polygon",
                points=f"{x},{y} {x + nw},{y + nh * 0.15} {x + nw},{y + nh * 0.85} {x},{y + nh}",
                **attrs,
            )
        else:
            el(
                "rect",
                x=x,
                y=y,
                width=nw,
                height=nh,
                rx=t.radius_pt if node.component != "register" else 0,
                **attrs,
            )
            if node.component in ("memory", "register"):
                el(
                    "line",
                    x1=x + 6,
                    y1=y,
                    x2=x + 6,
                    y2=y + nh,
                    stroke=t.foreground,
                    stroke_width=t.line_pt,
                )
            if node.component in ("pe_array", "dsp"):
                el(
                    "rect",
                    x=x + 3,
                    y=y + 3,
                    width=nw - 6,
                    height=nh - 6,
                    rx=2,
                    fill="none",
                    stroke=t.grid_color,
                    stroke_width=t.line_pt,
                )
        text(node.label, n["x"] + nw / 2, n["y"] + nh / 2, stable_id=node.id)
        for point in n["ports"].values():
            el(
                "rect",
                x=point["x"] + dx - 1.6,
                y=point["y"] + dy - 1.6,
                width=3.2,
                height=3.2,
                fill=t.foreground,
            )
    return tostring(root, encoding="unicode")


def render_diagram(ctx, directory):
    saved = compute_layout(ctx)
    editable = svg_figure(ctx, saved, outline=ctx.spec.output.text_mode == "outline")
    spec = ctx.spec
    if "svg" in spec.output.formats:
        (directory / f"{spec.id}.svg").write_text(editable, encoding="utf-8")
    if {"pdf", "png"} & set(spec.output.formats):
        try:
            import cairosvg
        except ImportError as e:
            raise FigdrawError(
                "PDF/PNG diagrams require pip install 'figdraw[diagrams]' and Cairo"
            ) from e
        # Use the same measured font outlines for conversion to avoid Cairo font substitution.
        outlined = svg_figure(ctx, saved, outline=True).encode()
        for fmt in ("pdf", "png"):
            if fmt in spec.output.formats:
                getattr(cairosvg, f"svg2{fmt}")(
                    bytestring=outlined,
                    write_to=str(directory / f"{spec.id}.{fmt}"),
                    dpi=spec.output.dpi,
                )
    (directory / "layout.json").write_text(
        json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"backend": "svg", "layout_engine": saved["engine"], "warnings": []}
