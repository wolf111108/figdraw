import pytest
import yaml

from figdraw.api import validate
from figdraw.cli import build, dependencies, main
from figdraw.errors import FigdrawError


@pytest.mark.parametrize("kind", ["bar", "line", "heatmap", "pie", "flowchart", "architecture"])
def test_init_and_validate(tmp_path, kind):
    file = tmp_path / f"{kind}.yaml"
    assert main(["init", kind, "--output", str(file)]) == 0
    assert main(["validate", str(file)]) == 0
    assert validate(file).spec.kind == kind
    assert main(["init", kind, "--output", str(file)]) == 2


def test_wrong_shortcut(tmp_path):
    file = tmp_path / "bar.yaml"
    main(["init", "bar", "--output", str(file)])
    assert main(["line", str(file)]) == 2


def test_batch_records_failure_and_duplicate_ids(example, tmp_path):
    good, bad = example(), example()
    bad["id"] = "bad"
    bad["data"]["inline"][0]["success"] = 2
    for name, spec in [("good", good), ("bad", bad)]:
        (tmp_path / f"{name}.yaml").write_text(yaml.safe_dump(spec))
    batch = {"schema_version": 1, "figures": ["good.yaml", "bad.yaml"]}
    file = tmp_path / "paper.yaml"
    file.write_text(yaml.safe_dump(batch))
    rows, report = build(file)
    assert [r["status"] for r in rows] == ["ok", "error"]
    assert report.is_file()
    batch["figures"] = ["good.yaml", "good.yaml"]
    file.write_text(yaml.safe_dump(batch))
    with pytest.raises(FigdrawError, match="duplicate figure"):
        build(file)


def test_watch_tracks_referenced_data(example, tmp_path):
    spec = example()
    spec["data"] = {"source": "records.csv"}
    file = tmp_path / "spec.yaml"
    file.write_text(yaml.safe_dump(spec))
    assert str(tmp_path / "records.csv") in dict(dependencies(file))
    before = dependencies(file)
    (tmp_path / "records.csv").write_text("task,method,success\n")
    assert before != dependencies(file)
