"""CLI and per-kind shortcuts all call the same public pipeline."""

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml
from pydantic import ValidationError

from figdraw import __version__
from figdraw.api import load_spec, read_config, render_file, validate, write_schema
from figdraw.diagrams.layout import worker_path
from figdraw.errors import FigdrawError
from figdraw.specs import BuildSpec
from figdraw.themes import PRESETS

KINDS = ("bar", "line", "heatmap", "pie", "flowchart", "architecture")
USER_ERRORS = (FigdrawError, ValidationError, OSError, yaml.YAMLError, json.JSONDecodeError)


def build(path, output_dir=None):
    path = Path(path).resolve()
    batch = BuildSpec.model_validate(read_config(path))
    paths = [(path.parent / p).resolve() for p in batch.figures]
    # Fail before output if two specs claim the same directory.
    parsed = []
    for p in paths:
        try:
            parsed.append((load_spec(p).id, None))
        except USER_ERRORS as e:
            parsed.append((None, str(e)))
    ids = [figure_id for figure_id, error in parsed if error is None]
    if len(set(ids)) != len(ids):
        raise FigdrawError("build contains duplicate figure IDs")
    output = Path(output_dir).resolve() if output_dir else path.parent / batch.output_directory
    records = []
    for figure, (_, parse_error) in zip(paths, parsed):
        if parse_error:
            records.append({"source": str(figure), "status": "error", "error": parse_error})
            continue
        try:
            result = render_file(figure, output_dir=output)
            records.append(
                {
                    "source": str(figure),
                    "id": result.id,
                    "status": "ok",
                    "manifest": str(result.manifest),
                }
            )
        except USER_ERRORS as e:
            records.append({"source": str(figure), "status": "error", "error": str(e)})
    output.mkdir(parents=True, exist_ok=True)
    report = output / "build-manifest.json"
    report.write_text(
        json.dumps({"schema_version": 1, "figures": records}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return records, report


def dependencies(path):
    paths = [path]
    try:
        spec = load_spec(path)
        for field in ("theme_file", "template_file", "project_style"):
            if getattr(spec, field):
                paths.append(path.parent / getattr(spec, field))
        if hasattr(spec, "data") and spec.data.source:
            paths.append(path.parent / spec.data.source)
        if hasattr(spec, "layout") and spec.layout.source:
            paths.append(path.parent / spec.layout.source)
    except USER_ERRORS:
        pass
    return tuple((str(p), p.stat().st_mtime_ns if p.exists() else None) for p in paths)


def preview(path, output, watch, interval):
    path = Path(path).resolve()
    last = None
    while True:
        current = dependencies(path)
        if current != last:
            last = current
            try:
                result = render_file(path, output_dir=output)
                print(f"Rendered {result.directory}", flush=True)
            except USER_ERRORS as e:
                if not watch:
                    raise
                print(f"figdraw: {e}", file=sys.stderr, flush=True)
        if not watch:
            return 0
        time.sleep(interval)


def parser():
    p = argparse.ArgumentParser(
        prog="figdraw", description="Versioned scientific figures from YAML/JSON"
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("render", *KINDS):
        s = sub.add_parser(name)
        s.add_argument("spec", type=Path)
        s.add_argument(
            "--output", type=Path, help="output parent directory; each figure uses its ID"
        )
    s = sub.add_parser("validate")
    s.add_argument("spec", type=Path)
    s = sub.add_parser("init")
    s.add_argument("kind", choices=KINDS)
    s.add_argument("--output", required=True, type=Path)
    s = sub.add_parser("schema")
    s.add_argument("--output", required=True, type=Path)
    s = sub.add_parser("build")
    s.add_argument("manifest", type=Path)
    s.add_argument("--output", type=Path)
    s = sub.add_parser("preview")
    s.add_argument("spec", type=Path)
    s.add_argument("--output", type=Path)
    s.add_argument("--watch", action="store_true")
    s.add_argument("--interval", type=float, default=0.5)
    sub.add_parser("doctor")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "init":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as f:
                f.write((PRESETS / "examples" / f"{args.kind}.yaml").read_text(encoding="utf-8"))
            print(args.output)
        elif args.command == "schema":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            write_schema(args.output)
            print(args.output)
        elif args.command == "validate":
            ctx = validate(args.spec)
            print(f"Valid: {ctx.spec.id} ({ctx.spec.kind})")
        elif args.command == "build":
            records, report = build(args.manifest, args.output)
            for row in records:
                print(
                    f"{row['status']}: {row['source']}"
                    + (f" — {row['error']}" if "error" in row else "")
                )
            print(f"Build manifest: {report}")
            return int(any(r["status"] != "ok" for r in records))
        elif args.command == "preview":
            if args.interval < 0.2:
                raise FigdrawError("watch interval must be at least 0.2 seconds")
            return preview(args.spec, args.output, args.watch, args.interval)
        elif args.command == "doctor":
            node = shutil.which("node")
            worker = worker_path()
            node_version = (
                subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
                if node
                else None
            )
            print(
                json.dumps(
                    {
                        "figdraw": __version__,
                        "python": sys.version.split()[0],
                        "node": node_version,
                        "cairosvg": importlib.util.find_spec("cairosvg") is not None,
                        "worker": str(worker),
                        "elkjs_installed": (worker.parent / "node_modules/elkjs").exists(),
                        "install_worker": f"npm ci --prefix {worker.parent}",
                    },
                    indent=2,
                )
            )
        else:
            if args.command in KINDS and load_spec(args.spec).kind != args.command:
                raise FigdrawError(f"{args.command} shortcut requires kind: {args.command}")
            result = render_file(args.spec, output_dir=args.output)
            print(result.directory)
        return 0
    except KeyboardInterrupt:
        return 0
    except USER_ERRORS as e:
        print(f"figdraw: {e}", file=sys.stderr)
        return 2
