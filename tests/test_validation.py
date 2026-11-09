import copy
import json

import pytest
import yaml

from figdraw import FigdrawError, json_schema, load_spec, validate
from figdraw.api import resolve


def test_union_schema_and_strict_fields(example):
    schema = json_schema()
    assert set(schema["discriminator"]["mapping"]) == {
        "bar",
        "line",
        "heatmap",
        "pie",
        "flowchart",
        "architecture",
    }
    spec = example()
    spec["options"]["legned"] = True
    with pytest.raises(ValueError, match="legned"):
        resolve(spec)


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), None, "", 1.2, -0.1])
def test_invalid_measurements(example, bad):
    spec = example()
    spec["data"]["inline"][0]["success"] = bad
    with pytest.raises(ValueError):
        resolve(spec)


def test_duplicate_data_and_missing_combinations(example):
    spec = example()
    spec["data"]["inline"].append(spec["data"]["inline"][0].copy())
    with pytest.raises(FigdrawError, match="duplicate data key"):
        resolve(spec)
    spec["data"]["inline"] = spec["data"]["inline"][:3]
    with pytest.raises(FigdrawError, match="missing category"):
        resolve(spec)


def test_data_xor_and_empty(example):
    spec = example()
    spec["data"]["source"] = "x.csv"
    with pytest.raises(ValueError, match="mutually exclusive"):
        resolve(spec)
    spec["data"] = {"inline": []}
    with pytest.raises(FigdrawError, match="nonempty"):
        resolve(spec)


def test_csv_relative_path_and_id_preservation(example, tmp_path, monkeypatch):
    spec = example()
    spec["data"] = {"source": "records.csv"}
    spec["encoding"]["x"].pop("order")
    (tmp_path / "records.csv").write_text("task,method,success\n001,baseline,.5\n001,proposed,.6\n")
    file = tmp_path / "spec.json"
    file.write_text(json.dumps(spec))
    monkeypatch.chdir("/")
    assert validate(file).data["categories"] == ["001"]


def test_duplicate_yaml_keys(tmp_path):
    file = tmp_path / "bad.yaml"
    file.write_text("kind: bar\nkind: pie\n")
    with pytest.raises(FigdrawError, match="duplicate configuration"):
        load_spec(file)


def test_duplicate_csv_headers(example, tmp_path):
    spec = example()
    spec["data"] = {"source": "records.csv"}
    (tmp_path / "records.csv").write_text("task,task,success\na,b,.5\n")
    with pytest.raises(FigdrawError, match="duplicate column"):
        resolve(spec, tmp_path)


def test_styles_stable_reorder_delete_unknown(example):
    spec = example()
    first = resolve(spec)
    spec["data"]["inline"].reverse()
    spec["encoding"]["series"]["order"].reverse()
    second = resolve(spec)
    assert first.styles == second.styles
    spec["data"]["inline"] = [r for r in spec["data"]["inline"] if r["method"] == "proposed"]
    spec["encoding"]["series"]["order"] = ["proposed"]
    assert resolve(spec).styles["proposed"] == first.styles["proposed"]
    for r in spec["data"]["inline"]:
        r["method"] = "new_method"
    spec["encoding"]["series"]["order"] = ["new_method"]
    with pytest.raises(FigdrawError, match="stable style"):
        resolve(spec)


def test_style_precedence_and_template_defaults(example, tmp_path):
    spec = example()
    spec["project_style"] = "style.yaml"
    (tmp_path / "style.yaml").write_text("series:\n  baseline: {color: '#112233'}\n")
    spec["overrides"] = {"series": {"baseline": {"color": "#445566"}}}
    spec["template"] = "bar.custom@1.0.0"
    spec["template_file"] = "template.yaml"
    (tmp_path / "template.yaml").write_text(
        yaml.safe_dump(
            {
                "id": spec["template"],
                "kind": "bar",
                "variant": "grouped",
                "defaults": {"orientation": "horizontal", "legend_location": "lower left"},
            }
        )
    )
    ctx = resolve(spec, tmp_path)
    assert ctx.styles["baseline"].color == "#445566"
    assert ctx.spec.options.orientation == "horizontal"
    assert ctx.spec.options.legend_location == "upper right"


def test_interval_metadata_and_bounds(example):
    spec = example("bar_interval")
    resolve(spec)
    del spec["encoding"]["interval"]["confidence"]
    with pytest.raises(ValueError, match="CI requires"):
        resolve(spec)
    spec = example("bar_interval")
    spec["data"]["inline"][0]["lower"] = 0.9
    with pytest.raises(ValueError, match="lower <= value"):
        resolve(spec)


def test_log_validation(example):
    spec = example("line")
    spec["encoding"]["x"]["scale"] = "log"
    with pytest.raises(FigdrawError, match="positive"):
        resolve(spec)


def test_line_sort_and_gap(example):
    spec = example("line")
    spec["data"]["inline"].reverse()
    with pytest.raises(FigdrawError, match="not increasing"):
        resolve(spec)
    spec["options"] = {"sort_x": True, "missing": "gap"}
    spec["data"]["inline"][0]["score"] = None
    assert resolve(spec).data["points"][0]["y"] is None


def test_heatmap_mask_zero_and_color_domain(example):
    spec = example("heatmap")
    spec["data"]["inline"].pop()
    with pytest.raises(FigdrawError, match="missing cells"):
        resolve(spec)
    spec["options"]["missing"] = "mask"
    spec["data"]["inline"][0]["score"] = 0
    assert resolve(spec).data["points"][0]["value"] == 0
    spec["options"]["vmax"] = 0.5
    with pytest.raises(FigdrawError, match="vmin/vmax"):
        resolve(spec)


@pytest.mark.parametrize("mutation", ["duplicate", "port", "direction", "width", "cycle"])
def test_graph_semantics(example, mutation):
    spec = example("architecture")
    graph = spec["graph"]
    if mutation == "duplicate":
        graph["nodes"].append(copy.deepcopy(graph["nodes"][0]))
    elif mutation == "port":
        graph["edges"][0]["source"]["port"] = "missing"
    elif mutation == "direction":
        graph["nodes"][0]["ports"][0]["direction"] = "input"
    elif mutation == "width":
        graph["nodes"][0]["ports"][0]["width_bits"] = 64
    else:
        graph["groups"][0]["parent"] = "compute"
    with pytest.raises(ValueError):
        resolve(spec)


def test_template_capacity_and_pie_zero(example):
    spec = example("pie")
    for r in spec["data"]["inline"]:
        r["bytes"] = 0
    with pytest.raises(FigdrawError, match="positive"):
        resolve(spec)
