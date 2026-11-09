import json
import re
import shutil
from xml.etree import ElementTree as ET

import matplotlib as mpl
import pytest
from PIL import Image

from figdraw import FigdrawError, render, render_file
from figdraw.diagrams.layout import worker_path

HAS_ELK = bool(shutil.which("node")) and (worker_path().parent / "node_modules/elkjs").exists()
elk = pytest.mark.skipif(not HAS_ELK, reason="npm ci --prefix packages/elk-worker required")


@pytest.mark.parametrize("name", ["bar", "bar_interval", "bar_stacked", "line", "heatmap", "pie"])
def test_exports_physical_size_and_portable_replay(example, tmp_path, name):
    spec = example(name)
    original = dict(mpl.rcParams)
    result = render(spec, output_dir=tmp_path / "out")
    assert dict(mpl.rcParams) == original
    width, height = spec["size"]["width_mm"], spec["size"]["height_mm"]
    svg = ET.parse(result.directory / f"{result.id}.svg").getroot()
    assert float(svg.attrib["width"].removesuffix("pt")) == pytest.approx(width * 72 / 25.4)
    png = Image.open(result.directory / f"{result.id}.png")
    assert png.width == pytest.approx(width / 25.4 * 300, abs=1)
    assert png.height == pytest.approx(height / 25.4 * 300, abs=1)
    pdf = (result.directory / f"{result.id}.pdf").read_bytes()
    box = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", pdf)
    assert box and float(box[1]) == pytest.approx(width * 72 / 25.4, abs=0.01)
    assert float(box[2]) == pytest.approx(height * 72 / 25.4, abs=0.01)
    manifest = json.loads(result.manifest.read_text())
    assert manifest["font"]["sha256"] and manifest["files"][f"{result.id}.png"]
    replay = tmp_path / "portable"
    shutil.copytree(result.directory, replay)
    result2 = render_file(replay / "resolved.yaml", output_dir=tmp_path / "reproduced")
    assert (result.directory / f"{result.id}.svg").read_bytes() == (
        result2.directory / f"{result.id}.svg"
    ).read_bytes()


@elk
@pytest.mark.parametrize("name", ["architecture", "flowchart", "pipeline"])
def test_diagram_round_trip_without_node(example, tmp_path, monkeypatch, name):
    spec = example(name)
    result = render(spec, output_dir=tmp_path / "out")
    saved = json.loads((result.directory / "layout.json").read_text())
    assert len(saved["geometry"]["edges"]) == len(spec["graph"]["edges"])
    svg = ET.parse(result.directory / f"{result.id}.svg").getroot()
    assert float(svg.attrib["width"].removesuffix("mm")) == spec["size"]["width_mm"]
    png = Image.open(result.directory / f"{result.id}.png")
    assert png.width == pytest.approx(spec["size"]["width_mm"] / 25.4 * 300, abs=1)
    monkeypatch.setenv("PATH", "")
    result2 = render_file(result.directory / "resolved.yaml", output_dir=tmp_path / "replay")
    assert (result.directory / f"{result.id}.svg").read_bytes() == (
        result2.directory / f"{result.id}.svg"
    ).read_bytes()


@elk
def test_fixed_stale_and_detached_geometry(example, tmp_path):
    spec = example("architecture")
    result = render(spec, output_dir=tmp_path)
    spec["layout"] = {"mode": "fixed", "source": str(result.directory / "layout.json")}
    spec["graph"]["nodes"][0]["label"] += " changed"
    with pytest.raises(FigdrawError, match="stale"):
        render(spec, output_dir=tmp_path)
    spec["graph"]["nodes"][0]["label"] = "Activation\nBuffer"
    layout = json.loads((result.directory / "layout.json").read_text())
    layout["geometry"]["nodes"]["act_buffer"]["x"] += 5
    (result.directory / "layout.json").write_text(json.dumps(layout))
    with pytest.raises(FigdrawError, match="declared side"):
        render(spec, output_dir=tmp_path)


@elk
def test_nested_groups_and_bus_ports(example, tmp_path):
    spec = example("architecture")
    spec["graph"]["groups"].append({"id": "outer", "label": "Accelerator"})
    spec["graph"]["groups"][0]["parent"] = "outer"
    spec["graph"]["nodes"][0]["group"] = "outer"
    spec["size"] = {"width_mm": 200, "height_mm": 100}
    result = render(spec, output_dir=tmp_path)
    saved = json.loads((result.directory / "layout.json").read_text())
    assert set(saved["geometry"]["groups"]) == {"outer", "compute"}


def test_no_silent_shrink_and_previous_result_preserved(example, tmp_path):
    spec = example("pipeline")
    result = render(spec, output_dir=tmp_path)
    old = result.manifest.read_bytes()
    spec["size"] = {"width_mm": 20, "height_mm": 20}
    with pytest.raises(FigdrawError, match="no automatic shrink"):
        render(spec, output_dir=tmp_path)
    assert result.manifest.read_bytes() == old


def test_untracked_file_protection(example, tmp_path):
    spec = example()
    target = tmp_path / spec["id"]
    target.mkdir()
    (target / f"{spec['id']}.svg").write_text("important content")
    with pytest.raises(FigdrawError, match="untracked"):
        render(spec, output_dir=tmp_path)
    assert (target / f"{spec['id']}.svg").read_text() == "important content"


def test_editable_vs_outline(example, tmp_path):
    for kind in ("bar", "pipeline"):
        spec = example(kind)
        spec["output"] = {"formats": ["svg"], "text_mode": "outline"}
        result = render(spec, output_dir=tmp_path)
        svg = ET.parse(result.outputs[0])
        assert not svg.findall(".//{http://www.w3.org/2000/svg}text")


def test_long_labels_report_overlap(example, tmp_path):
    spec = example()
    labels = {
        "Task A": "A very long category label that collides",
        "Task B": "Another very long category label",
    }
    for row in spec["data"]["inline"]:
        row["task"] = labels[row["task"]]
    spec["encoding"]["x"].pop("order")
    spec["size"] = {"width_mm": 85, "height_mm": 55}
    with pytest.raises(FigdrawError, match="overlap|exceeds canvas"):
        render(spec, output_dir=tmp_path)


@elk
def test_decision_edges_attach_to_diamond(example, tmp_path):
    spec = example("flowchart")
    result = render(spec, output_dir=tmp_path)
    geometry = json.loads((result.directory / "layout.json").read_text())["geometry"]
    n = geometry["nodes"]["validate"]
    for key in ("valid", "invalid"):
        p = geometry["edges"][key]["points"][0]
        assert abs((p["x"] - n["x"] - n["width"] / 2) / (n["width"] / 2)) + abs(
            (p["y"] - n["y"] - n["height"] / 2) / (n["height"] / 2)
        ) == pytest.approx(1)
