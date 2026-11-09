"""Read and normalize data without aggregation, imputation, or implicit sorting."""

import csv
import json
import math
from pathlib import Path

from figdraw.errors import FigdrawError


def number(value, field):
    if isinstance(value, bool):
        raise FigdrawError(f"{field}: boolean is not a numeric measurement")
    try:
        value = float(value)
    except (TypeError, ValueError) as e:
        raise FigdrawError(f"{field}: expected a finite number, got {value!r}") from e
    if not math.isfinite(value):
        raise FigdrawError(f"{field}: NaN/Infinity are not valid measurements")
    return value


def numeric(value, mapping):
    n = number(value, mapping.field)
    if mapping.unit in ("ratio", "percent"):
        top = 1 if mapping.unit == "ratio" else 100
        if not 0 <= n <= top:
            raise FigdrawError(f"{mapping.field}: {mapping.unit} must be in [0, {top}]")
    if mapping.scale == "log" and n <= 0:
        raise FigdrawError(f"{mapping.field}: log scale requires positive values")
    if mapping.domain and not mapping.domain[0] <= n <= mapping.domain[1]:
        raise FigdrawError(f"{mapping.field}: value {n} lies outside domain")
    return n


def read_records(data, base: Path):
    if data.inline is not None:
        rows = data.inline
    else:
        path = base / data.source
        fmt = data.format or path.suffix.lstrip(".").lower()
        if fmt == "csv":
            with path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                fields = reader.fieldnames or []
                if len(fields) != len(set(fields)):
                    raise FigdrawError("CSV has duplicate column names")
                rows = list(reader)
                if any(None in row for row in rows):
                    raise FigdrawError("CSV contains a row with too many columns")
        elif fmt == "json":
            rows = json.loads(path.read_text(encoding="utf-8"))
        else:
            raise FigdrawError("external data must use csv or json")
    if not isinstance(rows, list) or not rows or any(not isinstance(r, dict) for r in rows):
        raise FigdrawError("data must be a nonempty list of records")
    return rows


def category(row, mapping):
    value = row.get(mapping.field)
    if value is None or value == "" or isinstance(value, (dict, list, bool)):
        raise FigdrawError(f"{mapping.field}: expected a nonempty category ID")
    return str(value)


def ordered(values, mapping):
    natural = list(dict.fromkeys(values))
    if mapping is None or mapping.order is None:
        return natural
    if len(set(mapping.order)) != len(mapping.order) or set(mapping.order) != set(natural):
        raise FigdrawError(f"{mapping.field}.order must list each observed ID exactly once")
    return mapping.order


def normalize(spec, base):
    rows = read_records(spec.data, base)
    e, kind = spec.encoding, spec.kind
    points, keys = [], set()
    for row in rows:
        if kind in ("bar", "line"):
            series = category(row, e.series) if e.series else "default"
            x = category(row, e.x) if kind == "bar" else numeric(row.get(e.x.field), e.x)
            raw = row.get(e.y.field)
            missing = raw is None or raw == ""
            if missing and kind == "line" and spec.options.missing == "gap":
                y = None
            else:
                y = numeric(raw, e.y)
            p = {"x": x, "y": y, "series": series}
            key = (x, series)
            if kind == "bar" and e.interval:
                lo = numeric(row.get(e.interval.lower), e.y)
                hi = numeric(row.get(e.interval.upper), e.y)
                if not lo <= y <= hi:
                    raise FigdrawError("interval must satisfy lower <= value <= upper")
                p.update(lower=lo, upper=hi)
        elif kind == "heatmap":
            r, c = category(row, e.row), category(row, e.column)
            raw = row.get(e.value.field)
            if (raw is None or raw == "") and spec.options.missing == "mask":
                value = None
            else:
                value = numeric(raw, e.value)
                if not spec.options.vmin <= value <= spec.options.vmax:
                    raise FigdrawError("heatmap value outside explicit vmin/vmax")
            p, key = {"row": r, "column": c, "value": value}, (r, c)
        else:
            c = category(row, e.category)
            value = numeric(row.get(e.value.field), e.value)
            if value < 0:
                raise FigdrawError("pie values must be nonnegative")
            p, key = {"category": c, "value": value}, (c,)
        if key in keys:
            raise FigdrawError(f"duplicate data key {key}; aggregate explicitly before plotting")
        keys.add(key)
        points.append(p)
    result = {"points": points, "source_records": rows}
    if kind in ("bar", "line"):
        result["series"] = ordered([p["series"] for p in points], e.series)
        if kind == "bar":
            result["categories"] = ordered([p["x"] for p in points], e.x)
            if len(points) != len(result["series"]) * len(result["categories"]):
                raise FigdrawError("bar data has missing category/series combinations")
        else:
            for s in result["series"]:
                xs = [p["x"] for p in points if p["series"] == s]
                if xs != sorted(xs) and not spec.options.sort_x:
                    raise FigdrawError("line x is not increasing; set options.sort_x: true")
            if not any(p["y"] is not None for p in points):
                raise FigdrawError("line data contains no measurements")
    elif kind == "heatmap":
        result["rows"] = ordered([p["row"] for p in points], e.row)
        result["columns"] = ordered([p["column"] for p in points], e.column)
        if (
            len(points) != len(result["rows"]) * len(result["columns"])
            and spec.options.missing == "error"
        ):
            raise FigdrawError("heatmap has missing cells; use missing: mask explicitly")
    else:
        result["categories"] = ordered([p["category"] for p in points], e.category)
        total = sum(p["value"] for p in points)
        if total <= 0 or (not spec.options.normalize and not math.isclose(total, 1)):
            raise FigdrawError("pie total must be positive; normalize: false requires total = 1")
    return result
