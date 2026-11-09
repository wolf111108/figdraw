"""Fixed-size output and portable source snapshots, written through a staging directory."""

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from figdraw.diagrams.layout import digest, worker_path
from figdraw.errors import FigdrawError
from figdraw.specs import DiagramSpec


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass
class RenderResult:
    id: str
    directory: Path
    outputs: list[Path]
    manifest: Path


def version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def export(ctx, output_dir=None):
    from figdraw.charts import render_chart
    from figdraw.diagrams import render_diagram

    spec = ctx.spec
    destination = (
        Path(output_dir).resolve() if output_dir else (ctx.base / spec.output.directory).resolve()
    )
    target = destination / spec.id
    destination.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise FigdrawError("output directory cannot be a symbolic link")
    with tempfile.TemporaryDirectory(prefix=f".{spec.id}-", dir=destination) as temp:
        stage = Path(temp)
        details = (render_diagram if isinstance(spec, DiagramSpec) else render_chart)(ctx, stage)
        resolved = spec.model_dump(mode="json", exclude_none=True)
        resolved["theme_file"] = "theme.yaml"
        resolved["template_file"] = "template.yaml"
        resolved.pop("project_style", None)
        resolved["output"]["directory"] = "reproduced"
        if ctx.data:
            resolved["data"] = {"inline": ctx.data["source_records"]}
            resolved["overrides"]["series"] = {
                k: s.model_dump(exclude_none=True) for k, s in ctx.styles.items()
            }
            (stage / "data.snapshot.json").write_text(
                json.dumps(ctx.data["source_records"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            (stage / "normalized.json").write_text(
                json.dumps(ctx.data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        else:
            resolved["layout"]["mode"] = "fixed"
            resolved["layout"]["source"] = "layout.json"
        for name, value in [
            ("resolved.yaml", resolved),
            ("theme.yaml", ctx.theme.model_dump(mode="json")),
            ("template.yaml", ctx.template.model_dump(mode="json")),
        ]:
            (stage / name).write_text(
                yaml.safe_dump(value, sort_keys=False, allow_unicode=True), encoding="utf-8"
            )
        source_info = {
            "spec_sha256": sha(ctx.source) if ctx.source else digest(spec.model_dump(mode="json"))
        }
        if ctx.source:
            shutil.copyfile(ctx.source, stage / f"input{ctx.source.suffix}")
        if ctx.data and spec.data.source:
            path = ctx.base / spec.data.source
            source_info["data_sha256"] = sha(path)
            shutil.copyfile(path, stage / f"data.original{path.suffix}")
        dependencies = {
            name: version(name)
            for name in ("figdraw", "matplotlib", "numpy", "pydantic", "PyYAML", "CairoSVG")
        }
        lock_hashes = {}
        repo = Path(__file__).parents[3]
        for name, path in [
            ("uv.lock", repo / "uv.lock"),
            ("package-lock.json", worker_path().parent / "package-lock.json"),
        ]:
            if path.is_file():
                lock_hashes[name] = sha(path)
        files = {p.name: sha(p) for p in sorted(stage.iterdir()) if p.is_file()}
        manifest = {
            "schema_version": 1,
            "figure_id": spec.id,
            "kind": spec.kind,
            "size_mm": spec.size.model_dump(),
            "dpi": spec.output.dpi,
            "formats": spec.output.formats,
            "text_mode": spec.output.text_mode,
            "sources": source_info,
            "resolved_sha256": digest(resolved),
            "theme": {"id": ctx.theme.id, "sha256": digest(ctx.theme.model_dump())},
            "template": {"id": ctx.template.id, "sha256": digest(ctx.template.model_dump())},
            "font": ctx.font,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "dependencies": dependencies,
                "lock_sha256": lock_hashes,
            },
            "render": details,
            "files": files,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        # A failed render leaves the previous output intact. Only files previously
        # owned by a figdraw manifest may be replaced or removed.
        owned = set()
        if (target / "manifest.json").exists():
            old = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            if old.get("figure_id") != spec.id:
                raise FigdrawError("output directory belongs to a different figure")
            owned = {x for x in old.get("files", {}) if Path(x).name == x} | {"manifest.json"}
        new_names = {p.name for p in stage.iterdir()}
        if target.exists():
            conflicts = {p.name for p in target.iterdir()} & (new_names - owned)
            if conflicts:
                raise FigdrawError(f"output would overwrite untracked files: {sorted(conflicts)}")
        target.mkdir(parents=True, exist_ok=True)
        for p in stage.iterdir():
            os.replace(p, target / p.name)
        for name in owned - new_names:
            if (target / name).is_file():
                (target / name).unlink()
    return RenderResult(
        spec.id,
        target,
        [target / f"{spec.id}.{fmt}" for fmt in dict.fromkeys(spec.output.formats)],
        target / "manifest.json",
    )
