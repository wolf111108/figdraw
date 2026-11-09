"""Matplotlib adapter: one fixed-size canvas and one layout strategy."""

import warnings

import matplotlib as mpl
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import Normalize, TwoSlopeNorm
from matplotlib.figure import Figure
from matplotlib.text import Text
from matplotlib.ticker import PercentFormatter

from figdraw.errors import FigdrawError


def rc(theme, spec):
    t = theme.typography
    return {
        "font.family": t.family,
        "font.size": t.size_pt,
        "axes.titlesize": t.title_pt,
        "axes.labelsize": t.size_pt,
        "xtick.labelsize": t.size_pt,
        "ytick.labelsize": t.size_pt,
        "legend.fontsize": t.size_pt,
        "axes.linewidth": theme.line_pt,
        "lines.linewidth": theme.data_line_pt,
        "text.color": theme.foreground,
        "axes.labelcolor": theme.foreground,
        "xtick.color": theme.foreground,
        "ytick.color": theme.foreground,
        "axes.edgecolor": theme.foreground,
        "grid.color": theme.grid_color,
        "grid.linewidth": theme.line_pt * 0.6,
        "figure.facecolor": theme.background,
        "axes.facecolor": theme.background,
        "savefig.facecolor": theme.background,
        "savefig.bbox": None,
        "svg.fonttype": "none" if spec.output.text_mode == "editable" else "path",
        "svg.hashsalt": "figdraw-0.1",
        "pdf.fonttype": 42,
        "mathtext.fontset": t.math_font,
        "text.usetex": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }


def axis_scale(axis, mapping):
    if mapping.format == "percent":
        axis.set_major_formatter(PercentFormatter(1 if mapping.unit == "ratio" else 100))


def display_value(value, mapping, decimals=1):
    if mapping.format == "percent":
        value *= 100 if mapping.unit == "ratio" else 1
        return f"{value:.{decimals}f}%"
    return f"{value:g}"


def render_chart(ctx, directory):
    spec, theme, data, styles, template = ctx.spec, ctx.theme, ctx.data, ctx.styles, ctx.template
    points = data["points"]
    with mpl.rc_context(rc(theme, spec)), warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        fig = Figure(
            figsize=(spec.size.width_mm / 25.4, spec.size.height_mm / 25.4),
            dpi=spec.output.dpi,
            layout="constrained",
        )
        FigureCanvasAgg(fig)
        ax = fig.add_subplot()
        try:
            kind, e, o = spec.kind, spec.encoding, spec.options
            if kind == "bar":
                cats, series = data["categories"], data["series"]
                lookup = {(p["x"], p["series"]): p for p in points}
                pos = np.arange(len(cats))
                stacked = template.variant == "stacked"
                horizontal = o.orientation == "horizontal"
                width = template.group_width / (1 if stacked else len(series))
                bottom = np.zeros(len(cats))
                for i, s in enumerate(series):
                    ps = [lookup[c, s] for c in cats]
                    ys = np.array([p["y"] for p in ps])
                    st = styles[s]
                    error = (
                        np.array(
                            [[p["y"] - p["lower"] for p in ps], [p["upper"] - p["y"] for p in ps]]
                        )
                        if e.interval
                        else None
                    )
                    at = pos if stacked else pos + (i - (len(series) - 1) / 2) * width
                    common = dict(
                        color=st.color,
                        label=st.label or s,
                        hatch=st.hatch,
                        edgecolor=theme.background,
                        linewidth=0.5,
                        capsize=2,
                    )
                    if horizontal:
                        bars = ax.barh(
                            at,
                            ys,
                            height=width,
                            left=bottom if stacked else 0,
                            xerr=error,
                            **common,
                        )
                    else:
                        bars = ax.bar(
                            at,
                            ys,
                            width=width,
                            bottom=bottom if stacked else 0,
                            yerr=error,
                            **common,
                        )
                    if o.annotate:
                        ax.bar_label(
                            bars,
                            labels=[display_value(y, e.y) for y in ys],
                            padding=2,
                            label_type="center" if stacked else "edge",
                        )
                    if stacked:
                        bottom += ys
                (ax.set_yticks if horizontal else ax.set_xticks)(
                    pos, cats, rotation=o.label_rotation
                )
                (ax.set_xscale if horizontal else ax.set_yscale)(e.y.scale)
                if e.y.domain:
                    (ax.set_xlim if horizontal else ax.set_ylim)(*e.y.domain)
                axis_scale(ax.xaxis if horizontal else ax.yaxis, e.y)
                ax.grid(axis="x" if horizontal else "y", visible=o.grid)
            elif kind == "line":
                for s in data["series"]:
                    ps = [p for p in points if p["series"] == s]
                    if o.sort_x:
                        ps = sorted(ps, key=lambda p: p["x"])
                    st = styles[s]
                    ax.plot(
                        [p["x"] for p in ps],
                        [np.nan if p["y"] is None else p["y"] for p in ps],
                        color=st.color,
                        marker=st.marker,
                        linestyle=st.linestyle,
                        markersize=3.5,
                        label=st.label or s,
                    )
                for name in ("x", "y"):
                    mapping = getattr(e, name)
                    getattr(ax, f"set_{name}scale")(mapping.scale)
                    if mapping.domain:
                        getattr(ax, f"set_{name}lim")(*mapping.domain)
                    axis_scale(getattr(ax, f"{name}axis"), mapping)
                ax.tick_params(axis="x", labelrotation=o.label_rotation)
                ax.grid(visible=o.grid)
            elif kind == "heatmap":
                rows, cols = data["rows"], data["columns"]
                matrix = np.full((len(rows), len(cols)), np.nan)
                for p in points:
                    if p["value"] is not None:
                        matrix[rows.index(p["row"]), cols.index(p["column"])] = p["value"]
                cmap = mpl.colormaps[
                    theme.diverging if o.center is not None else theme.continuous
                ].copy()
                cmap.set_bad(theme.grid_color)
                norm = (
                    TwoSlopeNorm(o.center, o.vmin, o.vmax)
                    if o.center is not None
                    else Normalize(o.vmin, o.vmax)
                )
                im = ax.imshow(np.ma.masked_invalid(matrix), cmap=cmap, norm=norm, aspect="auto")
                ax.set_xticks(np.arange(len(cols)), cols, rotation=o.label_rotation)
                ax.set_yticks(np.arange(len(rows)), rows)
                if o.colorbar:
                    cb = fig.colorbar(im, ax=ax, pad=0.03)
                    axis_scale(cb.ax.yaxis, e.value)
                if o.annotate:
                    for i in range(len(rows)):
                        for j in range(len(cols)):
                            value = matrix[i, j]
                            if np.isnan(value):
                                ax.text(j, i, "—", ha="center", va="center")
                            else:
                                rgb = cmap(norm(value))[:3]
                                color = (
                                    "#FFFFFF"
                                    if np.dot(rgb, [0.2126, 0.7152, 0.0722]) < 0.5
                                    else "#172334"
                                )
                                label = (
                                    display_value(value, e.value, o.decimals)
                                    if e.value.format == "percent"
                                    else f"{value:.{o.decimals}f}"
                                )
                                ax.text(j, i, label, ha="center", va="center", color=color)
            else:
                cats = data["categories"]
                lookup = {p["category"]: p["value"] for p in points}
                ax.pie(
                    [lookup[c] for c in cats],
                    labels=[styles[c].label or c for c in cats],
                    colors=[styles[c].color for c in cats],
                    normalize=o.normalize,
                    startangle=o.startangle,
                    autopct=f"%.{o.decimals}f%%",
                    wedgeprops={"edgecolor": theme.background, "linewidth": theme.line_pt},
                    textprops={"fontsize": theme.typography.size_pt},
                )
            if kind in ("bar", "line"):
                ax.set_axisbelow(True)
                if o.legend and (e.series or len(data["series"]) > 1):
                    ax.legend(loc=o.legend_location, frameon=False)
            ax.set_title(spec.labels.title)
            if kind == "bar" and o.orientation == "horizontal":
                ax.set_xlabel(spec.labels.y)
                ax.set_ylabel(spec.labels.x)
            else:
                ax.set_xlabel(spec.labels.x)
                ax.set_ylabel(spec.labels.y)
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            bounds = fig.bbox
            for axis in (ax.xaxis, ax.yaxis):
                visible = [
                    label
                    for label in axis.get_ticklabels()
                    if label.get_visible() and label.get_text()
                ]
                boxes = [label.get_window_extent(renderer) for label in visible]
                for i, box in enumerate(boxes):
                    if any(box.overlaps(other) for other in boxes[i + 1 :]):
                        raise FigdrawError(
                            "tick labels overlap; enlarge size, add explicit line breaks or rotate labels"
                        )
            for text in fig.findobj(Text):
                if not text.get_visible() or not text.get_text():
                    continue
                b = text.get_window_extent(renderer)
                # Ignore tick artists outside explicit axis limits.
                if text.get_clip_on():
                    continue
                if b.x0 < -1 or b.y0 < -1 or b.x1 > bounds.x1 + 1 or b.y1 > bounds.y1 + 1:
                    raise FigdrawError(
                        f"label {text.get_text()!r} exceeds canvas; enlarge size or change template"
                    )
            for warning in seen:
                if "constrained_layout" in str(warning.message) or "Glyph" in str(warning.message):
                    raise FigdrawError(str(warning.message))
            for fmt in dict.fromkeys(spec.output.formats):
                metadata = (
                    {"Date": None}
                    if fmt == "svg"
                    else ({"CreationDate": None, "ModDate": None} if fmt == "pdf" else {})
                )
                fig.savefig(
                    directory / f"{spec.id}.{fmt}",
                    format=fmt,
                    dpi=spec.output.dpi,
                    bbox_inches=None,
                    metadata=metadata,
                )
            return {"backend": "matplotlib", "warnings": sorted({str(w.message) for w in seen})}
        finally:
            fig.clear()
