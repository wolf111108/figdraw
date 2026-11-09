"""ELK adapter and a deliberately narrow deterministic pipeline layout."""

import copy
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

from figdraw.errors import FigdrawError
from figdraw.themes import measure


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def worker_path():
    if os.environ.get("FIGDRAW_ELK_WORKER"):
        return Path(os.environ["FIGDRAW_ELK_WORKER"]).resolve()
    packaged = Path(__file__).parents[1] / "elk_worker" / "worker.cjs"
    return (
        packaged
        if packaged.exists()
        else Path(__file__).parents[3] / "packages/elk-worker/worker.cjs"
    )


def dimensions(ctx):
    result = {}
    t = ctx.theme
    for n in ctx.spec.graph.nodes:
        w, h = measure(n.label, t, ctx.font)
        if n.component == "junction":
            if n.label or n.ports:
                raise FigdrawError("junction uses an empty label and node endpoints (no ports)")
            w = h = 6
        else:
            factor = 2 if n.component == "decision" else 1
            w, h = max(48, w * factor + 2 * t.padding_pt), max(30, h * factor + 2 * t.padding_pt)
            sides = [p.side for p in n.ports]
            h = max(h, (max(sides.count("west"), sides.count("east")) + 1) * 12)
            w = max(w, (max(sides.count("north"), sides.count("south")) + 1) * 12)
        if (n.width_pt and n.width_pt < w) or (n.height_pt and n.height_pt < h):
            raise FigdrawError(f"node {n.id}: requested size is smaller than label/ports")
        result[n.id] = {"width": n.width_pt or w, "height": n.height_pt or h}
    return result


def signature(ctx, sizes):
    return digest(
        {
            "graph": ctx.spec.graph.model_dump(),
            "sizes": sizes,
            "font": ctx.font["sha256"],
            "typography": ctx.theme.typography.model_dump(),
            "padding": ctx.theme.padding_pt,
        }
    )


def elk_input(ctx, sizes):
    spec, theme = ctx.spec, ctx.theme
    objects = {}
    options = {
        "elk.algorithm": "layered",
        "elk.direction": spec.layout.direction.upper(),
        "elk.edgeRouting": "ORTHOGONAL",
        "elk.hierarchyHandling": "INCLUDE_CHILDREN",
        "elk.json.shapeCoords": "ROOT",
        "elk.json.edgeCoords": "ROOT",
        "elk.randomSeed": str(spec.layout.seed),
        "elk.spacing.nodeNode": str(spec.layout.spacing_pt),
        "elk.layered.spacing.nodeNodeBetweenLayers": str(spec.layout.spacing_pt),
        "elk.padding": f"[top={theme.padding_pt},left={theme.padding_pt},bottom={theme.padding_pt},right={theme.padding_pt}]",
    }
    root = {"id": "__figdraw_root__", "layoutOptions": options, "children": [], "edges": []}
    for g in spec.graph.groups:
        w, h = measure(g.label, theme, ctx.font)
        objects[g.id] = {
            "id": g.id,
            "children": [],
            "labels": [{"text": g.label, "width": w, "height": h}],
            "layoutOptions": {
                "elk.padding": f"[top={h + 20},left=14,bottom=14,right=14]",
                "elk.nodeLabels.placement": "INSIDE H_LEFT V_TOP",
            },
        }
    for n in spec.graph.nodes:
        objects[n.id] = {
            "id": n.id,
            **sizes[n.id],
            "ports": [
                {
                    "id": f"{n.id}:{p.id}",
                    "width": 0,
                    "height": 0,
                    "layoutOptions": {"elk.port.side": p.side.upper()},
                }
                for p in n.ports
            ],
            "layoutOptions": {"elk.portConstraints": "FIXED_SIDE"},
        }
    for g in spec.graph.groups:
        (objects[g.parent] if g.parent else root)["children"].append(objects[g.id])
    for n in spec.graph.nodes:
        (objects[n.group] if n.group else root)["children"].append(objects[n.id])
    for e in spec.graph.edges:

        def endpoint(ep):
            return f"{ep.node}:{ep.port}" if ep.port else ep.node

        edge = {"id": e.id, "sources": [endpoint(e.source)], "targets": [endpoint(e.target)]}
        if e.label:
            w, h = measure(e.label, theme, ctx.font)
            edge["labels"] = [
                {
                    "text": e.label,
                    "width": w,
                    "height": h,
                    "layoutOptions": {"elk.edgeLabels.placement": "CENTER"},
                }
            ]
        root["edges"].append(edge)
    return root


def run_elk(graph):
    worker = worker_path()
    try:
        result = subprocess.run(
            ["node", str(worker)],
            input=json.dumps(graph),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError as e:
        raise FigdrawError("Node.js >=20 is required for auto layout") from e
    except subprocess.TimeoutExpired as e:
        raise FigdrawError("ELK layout timed out after 60 seconds") from e
    if result.returncode:
        raise FigdrawError(
            f"ELK failed; run npm ci --prefix {worker.parent}\n{result.stderr[-1200:]}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise FigdrawError("ELK worker returned invalid JSON") from e


def flatten_elk(raw):
    # ROOT shape/edge coordinate options include ports and labels.
    result = {
        "width": raw["width"],
        "height": raw["height"],
        "nodes": {},
        "groups": {},
        "edges": {},
    }

    def walk(parent):
        for n in parent.get("children", []):
            entry = {k: n[k] for k in ("x", "y", "width", "height")}
            if "children" in n:
                entry["labels"] = n.get("labels", [])
                result["groups"][n["id"]] = entry
            else:
                entry["ports"] = {
                    p["id"].split(":", 1)[1]: {"x": p["x"], "y": p["y"]} for p in n.get("ports", [])
                }
                result["nodes"][n["id"]] = entry
            walk(n)
        for e in parent.get("edges", []):
            sections = e.get("sections", [])
            if len(sections) != 1:
                raise FigdrawError(
                    f"edge {e['id']}: expected one routed section, got {len(sections)}"
                )
            s = sections[0]
            result["edges"][e["id"]] = {
                "points": [s["startPoint"], *s.get("bendPoints", []), s["endPoint"]],
                "labels": e.get("labels", []),
            }

    walk(raw)
    return result


def pipeline(ctx, sizes):
    spec, pad = ctx.spec, ctx.theme.padding_pt
    if spec.graph.groups or spec.layout.direction not in ("right", "down"):
        raise FigdrawError("pipeline template supports ungrouped right/down chains only")
    nodes, edges = spec.graph.nodes, spec.graph.edges
    if len(edges) != len(nodes) - 1 or {(e.source.node, e.target.node) for e in edges} != {
        (a.id, b.id) for a, b in zip(nodes, nodes[1:])
    }:
        raise FigdrawError("pipeline template requires one edge between each consecutive node")
    horizontal = spec.layout.direction == "right"
    coordinate = pad
    extent = max(s["height" if horizontal else "width"] for s in sizes.values())
    result = {"nodes": {}, "edges": {}, "groups": {}}
    gaps = {}
    for e in edges:
        lw, lh = measure(e.label, ctx.theme, ctx.font)
        gaps[e.source.node] = max(spec.layout.spacing_pt, (lw if horizontal else lh) + 16)
    for n in nodes:
        w, h = sizes[n.id]["width"], sizes[n.id]["height"]
        x, y = (
            (coordinate, pad + (extent - h) / 2)
            if horizontal
            else (pad + (extent - w) / 2, coordinate)
        )
        ports = {}
        for side in ("west", "east", "north", "south"):
            same = [p for p in n.ports if p.side == side]
            for i, p in enumerate(same):
                f = (i + 1) / (len(same) + 1)
                px, py = {
                    "west": (x, y + h * f),
                    "east": (x + w, y + h * f),
                    "north": (x + w * f, y),
                    "south": (x + w * f, y + h),
                }[side]
                ports[p.id] = {"x": px, "y": py}
        result["nodes"][n.id] = {"x": x, "y": y, "width": w, "height": h, "ports": ports}
        coordinate += (w if horizontal else h) + gaps.get(n.id, 0)
    for e in edges:
        a, b = result["nodes"][e.source.node], result["nodes"][e.target.node]
        start = (
            a["ports"].get(e.source.port)
            if e.source.port
            else {
                "x": a["x"] + a["width"] if horizontal else a["x"] + a["width"] / 2,
                "y": a["y"] + a["height"] / 2 if horizontal else a["y"] + a["height"],
            }
        )
        end = (
            b["ports"].get(e.target.port)
            if e.target.port
            else {
                "x": b["x"] if horizontal else b["x"] + b["width"] / 2,
                "y": b["y"] + b["height"] / 2 if horizontal else b["y"],
            }
        )
        axis = "y" if horizontal else "x"
        side_source, side_target = ("east", "west") if horizontal else ("south", "north")
        for ep, required in [(e.source, side_source), (e.target, side_target)]:
            node = next(n for n in nodes if n.id == ep.node)
            if ep.port and next(p for p in node.ports if p.id == ep.port).side != required:
                raise FigdrawError("pipeline ports must face the next/previous node")
        if abs(start[axis] - end[axis]) > 0.01:
            raise FigdrawError("pipeline ports must be aligned; use auto layout for routing")
        lw, lh = measure(e.label, ctx.theme, ctx.font)
        label = {
            "text": e.label,
            "width": lw,
            "height": lh,
            "x": (start["x"] + end["x"]) / 2 - lw / 2 if horizontal else start["x"] + 4,
            "y": start["y"] - lh - 3 if horizontal else (start["y"] + end["y"]) / 2 - lh / 2,
        }
        result["edges"][e.id] = {"points": [start, end], "labels": [label] if e.label else []}
    result["width"] = max(n["x"] + n["width"] for n in result["nodes"].values()) + pad
    result["height"] = max(n["y"] + n["height"] for n in result["nodes"].values()) + pad
    return result


def project_outline(node, component, point, side):
    """Extend the terminal orthogonal segment from the ELK box to the actual symbol."""
    x, y = point["x"], point["y"]
    cx, cy = node["x"] + node["width"] / 2, node["y"] + node["height"] / 2
    a, b = node["width"] / 2, node["height"] / 2
    if component in ("decision", "junction"):
        if side in ("east", "west"):
            fraction = abs((y - cy) / b)
            radius = (
                max(0, 1 - fraction)
                if component == "decision"
                else math.sqrt(max(0, 1 - fraction**2))
            )
            x = cx + (1 if side == "east" else -1) * a * radius
        else:
            fraction = abs((x - cx) / a)
            radius = (
                max(0, 1 - fraction)
                if component == "decision"
                else math.sqrt(max(0, 1 - fraction**2))
            )
            y = cy + (1 if side == "south" else -1) * b * radius
    elif component == "mux" and side in ("north", "south"):
        inset = 0.15 * node["height"] * (x - node["x"]) / node["width"]
        y = node["y"] + inset if side == "north" else node["y"] + node["height"] - inset
    return {"x": x, "y": y}


def box_side(n, p):
    return min(
        {
            "west": abs(p["x"] - n["x"]),
            "east": abs(p["x"] - n["x"] - n["width"]),
            "north": abs(p["y"] - n["y"]),
            "south": abs(p["y"] - n["y"] - n["height"]),
        },
        key=lambda side: {
            "west": abs(p["x"] - n["x"]),
            "east": abs(p["x"] - n["x"] - n["width"]),
            "north": abs(p["y"] - n["y"]),
            "south": abs(p["y"] - n["y"] - n["height"]),
        }[side],
    )


def attach_symbol_outlines(ctx, geometry):
    nodes = {n.id: n for n in ctx.spec.graph.nodes}
    for edge in ctx.spec.graph.edges:
        points = geometry["edges"][edge.id]["points"]
        for endpoint, index in [(edge.source, 0), (edge.target, -1)]:
            n = geometry["nodes"][endpoint.node]
            component = nodes[endpoint.node].component
            points[index] = project_outline(n, component, points[index], box_side(n, points[index]))
    for n in ctx.spec.graph.nodes:
        actual = geometry["nodes"][n.id]
        for p in n.ports:
            actual["ports"][p.id] = project_outline(
                actual, n.component, actual["ports"][p.id], p.side
            )


def on_outline(node, component, point):
    x, y = point["x"], point["y"]
    cx, cy = node["x"] + node["width"] / 2, node["y"] + node["height"] / 2
    if component == "decision":
        return (
            abs(abs((x - cx) / (node["width"] / 2)) + abs((y - cy) / (node["height"] / 2)) - 1)
            < 0.01
        )
    if component == "junction":
        return (
            abs(((x - cx) / (node["width"] / 2)) ** 2 + ((y - cy) / (node["height"] / 2)) ** 2 - 1)
            < 0.01
        )
    if component == "mux":
        top = node["y"] + 0.15 * node["height"] * (x - node["x"]) / node["width"]
        bottom = (
            node["y"] + node["height"] - 0.15 * node["height"] * (x - node["x"]) / node["width"]
        )
        return (
            min(
                abs(x - node["x"]),
                abs(x - node["x"] - node["width"]),
                abs(y - top),
                abs(y - bottom),
            )
            < 0.1
        )
    return (
        min(
            abs(x - node["x"]),
            abs(x - node["x"] - node["width"]),
            abs(y - node["y"]),
            abs(y - node["y"] - node["height"]),
        )
        < 0.1
    )


def validate_geometry(ctx, geometry, sizes):
    spec = ctx.spec
    for kind, objects in [
        ("nodes", spec.graph.nodes),
        ("groups", spec.graph.groups),
        ("edges", spec.graph.edges),
    ]:
        if set(geometry.get(kind, {})) != {o.id for o in objects}:
            raise FigdrawError(f"layout {kind} IDs differ from graph")

    def finite(value):
        if isinstance(value, dict):
            for v in value.values():
                finite(v)
        elif isinstance(value, list):
            for v in value:
                finite(v)
        elif isinstance(value, (float, int)) and not math.isfinite(value):
            raise FigdrawError("layout contains nonfinite coordinates")

    finite(geometry)
    for n in spec.graph.nodes:
        actual = geometry["nodes"][n.id]
        if any(abs(actual[k] - sizes[n.id][k]) > 0.01 for k in ("width", "height")):
            raise FigdrawError(f"node {n.id}: fixed size changed; regenerate layout")
        if set(actual["ports"]) != {p.id for p in n.ports}:
            raise FigdrawError(f"node {n.id}: port set changed")
        for p in n.ports:
            point = actual["ports"][p.id]
            axis, boundary = {
                "east": ("x", actual["x"] + actual["width"]),
                "west": ("x", actual["x"]),
                "north": ("y", actual["y"]),
                "south": ("y", actual["y"] + actual["height"]),
            }[p.side]
            base_point = {**point, axis: boundary}
            expected = project_outline(actual, n.component, base_point, p.side)
            in_box = (
                actual["x"] - 0.1 <= point["x"] <= actual["x"] + actual["width"] + 0.1
                and actual["y"] - 0.1 <= point["y"] <= actual["y"] + actual["height"] + 0.1
            )
            if (
                not in_box
                or math.hypot(point["x"] - expected["x"], point["y"] - expected["y"]) > 0.1
            ):
                raise FigdrawError(f"node {n.id}:{p.id}: port is not on declared side")
    for edge in spec.graph.edges:
        points = geometry["edges"][edge.id]["points"]
        if len(points) < 2:
            raise FigdrawError(f"edge {edge.id}: missing route")
        for a, b in zip(points, points[1:]):
            if abs(a["x"] - b["x"]) > 0.1 and abs(a["y"] - b["y"]) > 0.1:
                raise FigdrawError(f"edge {edge.id}: route is not orthogonal")
        for ep, point in [(edge.source, points[0]), (edge.target, points[-1])]:
            n = geometry["nodes"][ep.node]
            if ep.port:
                p = n["ports"][ep.port]
                if math.hypot(p["x"] - point["x"], p["y"] - point["y"]) > 0.1:
                    raise FigdrawError(f"edge {edge.id}: route detached from port")
            else:
                x, y = point["x"], point["y"]
                in_box = (
                    n["x"] - 0.1 <= x <= n["x"] + n["width"] + 0.1
                    and n["y"] - 0.1 <= y <= n["y"] + n["height"] + 0.1
                )
                component = next(item.component for item in spec.graph.nodes if item.id == ep.node)
                on_edge = on_outline(n, component, point)
                if not in_box or not on_edge:
                    raise FigdrawError(f"edge {edge.id}: route detached from node")


def compute_layout(ctx):
    sizes = dimensions(ctx)
    expected = signature(ctx, sizes)
    mode = ctx.spec.layout.mode
    if mode == "fixed":
        saved = json.loads((ctx.base / ctx.spec.layout.source).read_text(encoding="utf-8"))
        if saved.get("signature") != expected:
            raise FigdrawError(
                "fixed layout is stale: topology, labels, fonts or node sizes changed; regenerate with mode: auto"
            )
        geometry = copy.deepcopy(saved["geometry"])
        engine = saved.get("engine", {})
    elif mode == "template":
        geometry, engine = pipeline(ctx, sizes), {"name": "pipeline", "version": "1.0.0"}
    else:
        raw = run_elk(elk_input(ctx, sizes))
        geometry, engine = flatten_elk(raw["graph"]), {"name": "elkjs", "version": raw["version"]}
    if mode != "fixed":
        attach_symbol_outlines(ctx, geometry)
    try:
        validate_geometry(ctx, geometry, sizes)
    except (KeyError, TypeError) as e:
        raise FigdrawError(f"invalid layout geometry: {e}") from e
    return {"schema_version": 1, "signature": expected, "engine": engine, "geometry": geometry}
