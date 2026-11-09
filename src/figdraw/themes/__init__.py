import hashlib
from pathlib import Path

import yaml
from matplotlib import colors, font_manager
from matplotlib.markers import MarkerStyle
from matplotlib.textpath import TextToPath
from pydantic import Field

from figdraw.errors import FigdrawError
from figdraw.specs import Model, SeriesStyle

PT_PER_MM = 72 / 25.4
PRESETS = Path(__file__).parents[1] / "presets"


class Typography(Model):
    family: str = "DejaVu Sans"
    size_pt: float = Field(default=8, ge=6)
    title_pt: float = Field(default=9, ge=6)
    math_font: str = "dejavusans"


class Theme(Model):
    id: str
    typography: Typography = Field(default_factory=Typography)
    background: str = "#FFFFFF"
    foreground: str = "#263445"
    grid_color: str = "#DDE3EB"
    node_fill: str = "#EDF3FA"
    group_fill: str = "#F6F8FB"
    control_color: str = "#B47D34"
    line_pt: float = Field(default=0.8, gt=0)
    data_line_pt: float = Field(default=1.2, gt=0)
    padding_pt: float = Field(default=10, ge=4)
    radius_pt: float = Field(default=4, ge=0)
    continuous: str = "viridis"
    diverging: str = "RdBu_r"
    series: dict[str, SeriesStyle] = Field(default_factory=dict)


class ProjectStyle(Model):
    series: dict[str, SeriesStyle]


def load_theme(spec, base):
    path = base / spec.theme_file if spec.theme_file else PRESETS / f"{spec.theme}.yaml"
    if not path.is_file():
        raise FigdrawError(f"theme {spec.theme!r} not found; provide theme_file")
    theme = Theme.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if theme.id != spec.theme:
        raise FigdrawError("theme_file id does not match the pinned theme version")
    for name in (
        "background",
        "foreground",
        "grid_color",
        "node_fill",
        "group_fill",
        "control_color",
    ):
        if not colors.is_color_like(getattr(theme, name)):
            raise FigdrawError(f"invalid theme color: {name}")
    try:
        font_path = font_manager.findfont(theme.typography.family, fallback_to_default=False)
    except ValueError as e:
        raise FigdrawError(f"font {theme.typography.family!r} is not installed") from e
    font = {
        "family": font_manager.FontProperties(fname=font_path).get_name(),
        "sha256": hashlib.sha256(Path(font_path).read_bytes()).hexdigest(),
        "file": font_path,
    }
    return theme, font


def check_glyphs(strings, font, math_text=False):
    import re

    chars = font_manager.get_font(font["file"]).get_charmap()
    text = "".join(strings)
    if math_text:
        text = re.sub(r"\$[^$]*\$", "", text)
    missing = sorted({c for c in text if not c.isspace() and ord(c) not in chars})
    if missing:
        raise FigdrawError(
            f"font {font['family']} lacks glyphs {''.join(missing)!r}; select an installed font in theme_file"
        )


def measure(text, theme, font):
    prop = font_manager.FontProperties(fname=font["file"], size=theme.typography.size_pt)
    return max(
        (TextToPath().get_text_width_height_descent(t, prop, False)[0] for t in text.split("\n")),
        default=0,
    ), len(text.split("\n")) * theme.typography.size_pt * 1.35


def styles(spec, theme, base, ids):
    mapping = dict(theme.series)
    if spec.project_style:
        raw = yaml.safe_load((base / spec.project_style).read_text(encoding="utf-8"))
        mapping.update(ProjectStyle.model_validate(raw).series)
    mapping.update(spec.overrides.series)
    result = {}
    for key in ids:
        if key not in mapping:
            raise FigdrawError(
                f"series {key!r} needs a stable style in project_style or overrides.series"
            )
        if not colors.is_color_like(mapping[key].color):
            raise FigdrawError(f"series {key!r}: invalid color")
        try:
            MarkerStyle(mapping[key].marker)
        except ValueError as e:
            raise FigdrawError(f"series {key!r}: invalid marker") from e
        if mapping[key].hatch and set(mapping[key].hatch) - set("/\\|-+xoO.*"):
            raise FigdrawError(f"series {key!r}: invalid hatch")
        result[key] = mapping[key]
    return result
