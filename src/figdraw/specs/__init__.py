"""Strict public input protocol; JSON Schema is generated from these models."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

ID = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]*$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class Size(Model):
    width_mm: float = Field(default=85, gt=0, le=2000)
    height_mm: float = Field(default=55, gt=0, le=2000)


class Output(Model):
    formats: list[Literal["svg", "pdf", "png"]] = Field(
        default_factory=lambda: ["svg", "pdf", "png"], min_length=1
    )
    dpi: int = Field(default=300, ge=72, le=1200)
    directory: str = "output"
    text_mode: Literal["editable", "outline"] = "editable"


class SeriesStyle(Model):
    color: str
    label: str | None = None
    marker: str = "o"
    linestyle: Literal["-", "--", "-.", ":"] = "-"
    hatch: str | None = None


class Offset(Model):
    dx_pt: float = 0
    dy_pt: float = 0


class Overrides(Model):
    series: dict[str, SeriesStyle] = Field(default_factory=dict)
    labels: dict[str, Offset] = Field(default_factory=dict)


class Labels(Model):
    title: str = ""
    x: str = ""
    y: str = ""


class Common(Model):
    schema_version: Literal[1]
    id: ID
    template: str
    theme: str = "paper@1.0.0"
    theme_file: str | None = None
    template_file: str | None = None
    project_style: str | None = None
    size: Size = Field(default_factory=Size)
    labels: Labels = Field(default_factory=Labels)
    overrides: Overrides = Field(default_factory=Overrides)
    output: Output = Field(default_factory=Output)


class Data(Model):
    inline: list[dict[str, Any]] | None = None
    source: str | None = None
    format: Literal["csv", "json"] | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.inline is None) == (self.source is None):
            raise ValueError("data.inline and data.source are mutually exclusive; supply one")
        if self.inline is not None and self.format is not None:
            raise ValueError("data.format only applies to an external source")
        return self


class Category(Model):
    field: str
    order: list[str] | None = None


class Numeric(Model):
    field: str
    unit: Literal["number", "ratio", "percent"] = "number"
    domain: tuple[float, float] | None = None
    format: Literal["number", "percent"] = "number"
    scale: Literal["linear", "log"] = "linear"

    @model_validator(mode="after")
    def domain_valid(self):
        if self.domain and self.domain[0] >= self.domain[1]:
            raise ValueError("domain must be strictly increasing")
        if self.scale == "log" and self.domain and self.domain[0] <= 0:
            raise ValueError("log domain must be positive")
        if self.format == "percent" and self.unit == "number":
            raise ValueError("percent formatting requires unit: ratio or percent")
        return self


class Interval(Model):
    lower: str
    upper: str
    meaning: Literal["SD", "SEM", "CI", "range"]
    confidence: float | None = Field(default=None, gt=0, lt=1)
    sample_size: int = Field(gt=0)
    method: str = Field(min_length=1)

    @model_validator(mode="after")
    def ci(self):
        if self.meaning == "CI" and self.confidence is None:
            raise ValueError("CI requires confidence")
        if self.meaning != "CI" and self.confidence is not None:
            raise ValueError("confidence is only valid for CI")
        return self


class BarEncoding(Model):
    x: Category
    y: Numeric
    series: Category | None = None
    interval: Interval | None = None


class LineEncoding(Model):
    x: Numeric
    y: Numeric
    series: Category | None = None


class HeatEncoding(Model):
    row: Category
    column: Category
    value: Numeric


class PieEncoding(Model):
    category: Category
    value: Numeric


class AxisOptions(Model):
    legend: bool = True
    legend_location: Literal["best", "upper left", "upper right", "lower left", "lower right"] = (
        "best"
    )
    grid: bool = True
    label_rotation: float = Field(default=0, ge=-90, le=90)


class BarOptions(AxisOptions):
    annotate: bool = False
    orientation: Literal["vertical", "horizontal"] = "vertical"


class LineOptions(AxisOptions):
    sort_x: bool = False
    missing: Literal["error", "gap"] = "error"


class HeatOptions(Model):
    annotate: bool = True
    missing: Literal["error", "mask"] = "error"
    vmin: float
    vmax: float
    center: float | None = None
    decimals: int = Field(default=2, ge=0, le=6)
    colorbar: bool = True
    label_rotation: float = Field(default=0, ge=-90, le=90)

    @model_validator(mode="after")
    def limits(self):
        if self.vmin >= self.vmax:
            raise ValueError("heatmap requires vmin < vmax")
        if self.center is not None and not self.vmin < self.center < self.vmax:
            raise ValueError("center must lie strictly inside vmin/vmax")
        return self


class PieOptions(Model):
    normalize: bool = True
    decimals: int = Field(default=1, ge=0, le=4)
    startangle: float = 90


class BarSpec(Common):
    kind: Literal["bar"]
    data: Data
    encoding: BarEncoding
    options: BarOptions = Field(default_factory=BarOptions)


class LineSpec(Common):
    kind: Literal["line"]
    data: Data
    encoding: LineEncoding
    options: LineOptions = Field(default_factory=LineOptions)


class HeatmapSpec(Common):
    kind: Literal["heatmap"]
    data: Data
    encoding: HeatEncoding
    options: HeatOptions


class PieSpec(Common):
    kind: Literal["pie"]
    data: Data
    encoding: PieEncoding
    options: PieOptions = Field(default_factory=PieOptions)


class Port(Model):
    id: ID
    side: Literal["east", "west", "north", "south"]
    direction: Literal["input", "output", "inout"]
    width_bits: int = Field(default=1, gt=0)


class Node(Model):
    id: ID
    component: Literal[
        "block",
        "memory",
        "register",
        "mux",
        "dsp",
        "pe",
        "pe_array",
        "controller",
        "accumulator",
        "decision",
        "junction",
    ] = "block"
    label: str
    group: ID | None = None
    ports: list[Port] = Field(default_factory=list)
    width_pt: float | None = Field(default=None, gt=0)
    height_pt: float | None = Field(default=None, gt=0)


class Group(Model):
    id: ID
    label: str
    parent: ID | None = None


class Endpoint(Model):
    node: ID
    port: ID | None = None


class Edge(Model):
    id: ID
    source: Endpoint
    target: Endpoint
    role: Literal["data", "control"] = "data"
    label: str = ""


class Graph(Model):
    nodes: list[Node] = Field(min_length=1)
    edges: list[Edge] = Field(default_factory=list)
    groups: list[Group] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        ids = [x.id for x in [*self.nodes, *self.groups, *self.edges]]
        if len(ids) != len(set(ids)):
            raise ValueError("node, group and edge IDs must be globally unique")
        nodes = {n.id: n for n in self.nodes}
        groups = {g.id: g for g in self.groups}
        for g in self.groups:
            seen = {g.id}
            parent = g.parent
            while parent:
                if parent not in groups or parent in seen:
                    raise ValueError(f"group {g.id}: missing parent or hierarchy cycle")
                seen.add(parent)
                parent = groups[parent].parent
        for n in self.nodes:
            if n.group and n.group not in groups:
                raise ValueError(f"node {n.id}: unknown group {n.group}")
            if len({p.id for p in n.ports}) != len(n.ports):
                raise ValueError(f"node {n.id}: duplicate port IDs")
        for e in self.edges:
            ports = []
            for which, ep in [("source", e.source), ("target", e.target)]:
                if ep.node not in nodes:
                    raise ValueError(f"edge {e.id}: unknown node {ep.node}")
                p = next((p for p in nodes[ep.node].ports if p.id == ep.port), None)
                if ep.port and p is None:
                    raise ValueError(f"edge {e.id}: unknown port {ep.node}:{ep.port}")
                if p and p.direction == ("input" if which == "source" else "output"):
                    raise ValueError(f"edge {e.id}: invalid {which} port direction")
                ports.append(p)
            if all(ports) and ports[0].width_bits != ports[1].width_bits:
                raise ValueError(f"edge {e.id}: bus width mismatch")
        return self


class Layout(Model):
    mode: Literal["auto", "template", "fixed"] = "auto"
    engine: Literal["elk"] = "elk"
    direction: Literal["right", "down", "left", "up"] = "right"
    routing: Literal["orthogonal"] = "orthogonal"
    source: str | None = None
    spacing_pt: float = Field(default=28, ge=12)
    seed: int = 1
    template: Literal["pipeline"] = "pipeline"

    @model_validator(mode="after")
    def fixed_source(self):
        if (self.mode == "fixed") != (self.source is not None):
            raise ValueError("layout.source is required only for fixed layout")
        return self


class DiagramSpec(Common):
    kind: Literal["flowchart", "architecture"]
    graph: Graph
    layout: Layout = Field(default_factory=Layout)


FigureSpec = Annotated[
    BarSpec | LineSpec | HeatmapSpec | PieSpec | DiagramSpec, Field(discriminator="kind")
]
SPEC_ADAPTER = TypeAdapter(FigureSpec)


class BuildSpec(Model):
    schema_version: Literal[1]
    figures: list[str] = Field(min_length=1)
    output_directory: str = "output"
