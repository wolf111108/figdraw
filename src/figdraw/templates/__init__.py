"""Small versioned registry, separate from backend code."""

import yaml
from pydantic import Field

from figdraw.errors import FigdrawError
from figdraw.specs import Model


class Template(Model):
    id: str
    kind: str
    variant: str
    max_categories: int = Field(default=16, gt=0)
    max_series: int = Field(default=6, gt=0)
    max_nodes: int = Field(default=60, gt=0)
    group_width: float = Field(default=0.76, gt=0, lt=1)
    defaults: dict = Field(default_factory=dict)


REGISTRY = {}


def register(template: Template):
    if template.id in REGISTRY:
        raise FigdrawError(f"template {template.id} already registered")
    REGISTRY[template.id] = template


for kind, variant in [
    ("bar", "grouped"),
    ("bar", "stacked"),
    ("line", "standard"),
    ("heatmap", "annotated"),
    ("pie", "standard"),
    ("flowchart", "standard"),
    ("architecture", "block"),
]:
    register(Template(id=f"{kind}.{variant}@1.0.0", kind=kind, variant=variant))


def resolve_template(spec, base):
    if spec.template_file:
        template = Template.model_validate(
            yaml.safe_load((base / spec.template_file).read_text(encoding="utf-8"))
        )
    else:
        template = REGISTRY.get(spec.template)
    if template is None or template.id != spec.template or template.kind != spec.kind:
        raise FigdrawError(f"unknown or incompatible template {spec.template!r}")
    supported = {(t.kind, t.variant) for t in REGISTRY.values()}
    if (template.kind, template.variant) not in supported:
        raise FigdrawError("custom template requires a supported rendering variant")
    if hasattr(spec, "options"):
        options = type(spec.options).model_validate(
            {**template.defaults, **spec.options.model_dump(exclude_unset=True)}
        )
        spec = spec.model_copy(update={"options": options})
    elif template.defaults:
        raise FigdrawError("diagram templates do not accept chart option defaults")
    return spec, template
