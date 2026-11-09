"""Public load -> validate -> resolve -> normalize -> render pipeline."""

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from figdraw.data import normalize
from figdraw.errors import FigdrawError
from figdraw.specs import SPEC_ADAPTER, Common, DiagramSpec
from figdraw.templates import resolve_template
from figdraw.themes import check_glyphs, load_theme, styles


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently dropping user input."""


def _mapping(loader, node, deep=False):
    pairs = loader.construct_pairs(node, deep=deep)
    result = {}
    for key, value in pairs:
        if key in result:
            raise FigdrawError(f"duplicate configuration key: {key}")
        result[key] = value
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def read_config(path):
    return yaml.load(Path(path).read_text(encoding="utf-8"), Loader=UniqueLoader)


def load_spec(path):
    """Return a strict typed spec. Use render_file to retain its source directory."""
    return SPEC_ADAPTER.validate_python(read_config(path))


@dataclass
class Context:
    spec: Common
    base: Path
    source: Path | None
    theme: object
    template: object
    font: dict
    data: dict | None
    styles: dict


def resolve(spec, base_dir=None, source=None):
    if not isinstance(spec, Common):
        spec = SPEC_ADAPTER.validate_python(spec)
    # Revalidate model instances as well, including model_copy(update=...).
    spec = SPEC_ADAPTER.validate_python(spec.model_dump(exclude_unset=True))
    base = Path(base_dir or ".").resolve()
    spec, template = resolve_template(spec, base)
    theme, font = load_theme(spec, base)
    texts = [spec.labels.title, spec.labels.x, spec.labels.y]
    if isinstance(spec, DiagramSpec):
        data, mapping = None, {}
        texts.extend(x.label for x in [*spec.graph.nodes, *spec.graph.groups, *spec.graph.edges])
        ids = {x.id for x in [*spec.graph.nodes, *spec.graph.groups, *spec.graph.edges]}
        if set(spec.overrides.labels) - ids:
            raise FigdrawError("overrides.labels contains unknown graph IDs")
        if spec.overrides.series:
            raise FigdrawError("diagram style overrides use themes; series is for charts")
        if len(spec.graph.nodes) > template.max_nodes:
            raise FigdrawError("template node capacity exceeded")
    else:
        if spec.overrides.labels:
            raise FigdrawError("label offsets currently apply only to diagram stable IDs")
        data = normalize(spec, base)
        series = data.get("series", data.get("categories", []) if spec.kind == "pie" else [])
        mapping = styles(spec, theme, base, series)
        for name in ("categories", "rows", "columns"):
            texts.extend(data.get(name, []))
            if len(data.get(name, [])) > template.max_categories:
                raise FigdrawError(
                    "template category capacity exceeded; use an explicit wider template"
                )
        if len(data.get("series", [])) > template.max_series:
            raise FigdrawError("template series capacity exceeded")
        texts.extend(s.label or key for key, s in mapping.items())
        if spec.kind == "bar" and template.variant == "stacked":
            if spec.encoding.interval or spec.encoding.y.scale == "log":
                raise FigdrawError("stacked bars do not support intervals or log scale")
            if any(p["y"] < 0 for p in data["points"]):
                raise FigdrawError("stacked bars require nonnegative values")
            for c in data["categories"]:
                total = sum(p["y"] for p in data["points"] if p["x"] == c)
                if spec.encoding.y.domain and total > spec.encoding.y.domain[1]:
                    raise FigdrawError("stacked total exceeds y domain")
        if spec.kind == "heatmap" and spec.encoding.value.scale == "log":
            raise FigdrawError("heatmap currently supports linear color scales only")
        if spec.kind == "pie" and (
            spec.encoding.value.scale != "linear" or spec.encoding.value.domain
        ):
            raise FigdrawError("pie does not support axis domains or logarithmic scales")
    check_glyphs(texts, font, math_text=not isinstance(spec, DiagramSpec))
    return Context(spec, base, source, theme, template, font, data, mapping)


def validate(path):
    """Validate input, data, styles, and graph references, without starting a backend."""
    path = Path(path).resolve()
    return resolve(load_spec(path), path.parent, path)


def render(spec, *, base_dir=None, output_dir=None):
    """Render a mapping or typed spec. Relative references use explicit base_dir."""
    from figdraw.export import export

    return export(resolve(spec, base_dir), output_dir)


def render_file(path, *, output_dir=None):
    """Render a YAML/JSON file; all relative paths are anchored to that file."""
    from figdraw.export import export

    return export(validate(path), output_dir)


def json_schema():
    return SPEC_ADAPTER.json_schema()


def write_schema(path):
    Path(path).write_text(
        json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
