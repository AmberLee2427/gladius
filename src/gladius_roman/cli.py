"""Command-line configuration, validation, demonstration and execution."""

import argparse
import json
import sys
from importlib.resources import files
from pathlib import Path

import yaml

from . import __version__
from .config import RunConfig, load_config
from .demo import create_demo
from .environment import load_environment
from .pipeline import run


def main(argv=None):
    """Return zero on success, nonzero for invalid config or any failed exposure."""
    parser = argparse.ArgumentParser(prog="gladius", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-config", help="write an annotated YAML configuration")
    init.add_argument("path", type=Path)
    validate = commands.add_parser("validate", help="validate YAML without querying or downloading")
    validate.add_argument("config", type=Path)
    validate.add_argument("--targets", type=Path, help="replace YAML targets with a target CSV")
    validate.add_argument(
        "--resolved", type=Path, help="write resolved defaults and absolute paths"
    )
    schema = commands.add_parser("config-schema", help="write JSON Schema for editor completion")
    schema.add_argument("path", type=Path)
    execute = commands.add_parser("run", help="extract configured targets from selected exposures")
    execute.add_argument("config", type=Path)
    execute.add_argument("--targets", type=Path, help="replace YAML targets with a target CSV")
    gui = commands.add_parser("gui", help="serve the local configuration builder and run monitor")
    gui.add_argument("--port", type=int, default=8768)
    gui.add_argument("--workspace", type=Path, default=Path.cwd())
    demo = commands.add_parser("demo", help="build and run a small synthetic offline example")
    demo.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "gui":
            from .web import serve

            serve(args.workspace, port=args.port)
        elif args.command == "init-config":
            with args.path.open("x") as stream:
                stream.write(files("gladius_roman").joinpath("data/example.yaml").read_text())
            print(args.path.resolve())
        elif args.command == "config-schema":
            with args.path.open("x") as stream:
                json.dump(RunConfig.model_json_schema(), stream, indent=2)
                stream.write("\n")
        elif args.command == "validate":
            config = load_config(args.config, targets_path=args.targets)
            if args.resolved:
                with args.resolved.open("x") as stream:
                    stream.write(yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False))
            print("Configuration is valid (no input access or network operations performed).")
        else:
            path = create_demo(args.directory) if args.command == "demo" else args.config
            load_environment(path.expanduser().resolve().parent)
            manifest = run(load_config(path, targets_path=getattr(args, "targets", None)))
            print(f"Manifest: {manifest}")
            return 0 if json.loads(manifest.read_text())["status"] == "complete" else 1
    except (Exception, KeyboardInterrupt) as exc:
        print(f"gladius: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    return 0
