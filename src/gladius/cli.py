"""Command-line configuration, validation, demonstration and execution."""

import argparse
import getpass
import json
import sys
import warnings
from importlib.resources import files
from pathlib import Path

import yaml
from dotenv import dotenv_values

from . import __version__
from .config import RunConfig, load_config
from .demo import create_demo, create_mast_demo
from .environment import load_environment, save_mast_token
from .pipeline import run


def main(argv=None):
    """Return zero on success, nonzero for invalid config or any failed exposure."""
    parser = argparse.ArgumentParser(prog="gladius", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    tutorial = parser.add_mutually_exclusive_group()
    tutorial.add_argument(
        "--nexus-tutorial",
        action="store_true",
        help="copy a Nexus tutorial into the current directory and open it in JupyterLab",
    )
    tutorial.add_argument(
        "--tutorial",
        action="store_true",
        help="copy a local tutorial into the current directory and start JupyterLab",
    )
    parser.add_argument(
        "--no-open", action="store_true", help="copy a tutorial without opening JupyterLab"
    )
    commands = parser.add_subparsers(dest="command")
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
    execute.add_argument("--env-file", type=Path, help="load credentials from this dotenv file")
    gui = commands.add_parser("gui", help="serve the local configuration builder and run monitor")
    gui.add_argument("--port", type=int, default=8768)
    gui.add_argument(
        "--public-url", help="full browser URL behind a trusted Jupyter proxy, ending /proxy/PORT/"
    )
    gui.add_argument(
        "--nexus",
        action="store_true",
        help="use the Roman Nexus host with this JupyterHub server prefix",
    )
    gui.add_argument(
        "--iframe-origin",
        help="allow notebook embedding from this exact origin, or self for the Jupyter proxy",
    )
    gui.add_argument("--workspace", type=Path, default=Path.cwd())
    gui.add_argument("--env-file", type=Path, help="load credentials from this dotenv file")
    token = commands.add_parser("token", help="save a MAST token using a hidden prompt")
    token.add_argument(
        "--env-file", type=Path, default=Path(".env"), help="destination (default: .env)"
    )
    token.add_argument(
        "--force", action="store_true", help="replace an existing token without asking"
    )
    demo = commands.add_parser("demo", help="run a real MAST or synthetic offline example")
    demo.add_argument(
        "example", help="mast-demo for real data; otherwise an offline demo directory"
    )
    demo.add_argument("--directory", type=Path, help="MAST demo destination (default: ./mast-demo)")
    demo.add_argument(
        "--env-file", type=Path, help="credentials (default: .env in the launch directory)"
    )
    demo.add_argument(
        "--max-parent-mib", type=float, help="MAST advertised parent size limit (default: 512)"
    )
    args = parser.parse_args(argv)
    is_tutorial = args.nexus_tutorial or args.tutorial
    if is_tutorial and args.command:
        parser.error("Choose a tutorial flag or a subcommand, not both")
    if not is_tutorial and (args.no_open or not args.command):
        parser.error("Choose a subcommand, --tutorial or --nexus-tutorial")
    try:
        if is_tutorial:
            from .tutorials import open_tutorial, write_tutorial

            path = write_tutorial(Path.cwd(), nexus=args.nexus_tutorial)
            print(f"Tutorial: {path}")
            if not args.no_open:
                print(open_tutorial(path, nexus=args.nexus_tutorial))
            return 0
        if args.command == "token":
            path = args.env_file.expanduser().absolute()
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ValueError(
                    "The environment destination must be a regular file, not a symlink"
                )
            if not path.parent.is_dir():
                raise FileNotFoundError(f"Environment file directory does not exist: {path.parent}")
            if dotenv_values(path, interpolate=False).get("MAST_API_TOKEN") and not args.force:
                if input(f"Replace the MAST token in {path}? [y/N] ").strip().lower() not in {
                    "y",
                    "yes",
                }:
                    print("Token unchanged.")
                    return 0
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                try:
                    value = getpass.getpass("MAST API token (hidden): ")
                except getpass.GetPassWarning as exc:
                    raise ValueError(
                        "A terminal with hidden input is required; edit .env directly instead"
                    ) from exc
            saved = save_mast_token(value, path)
            print(f"MAST token saved to {saved}. Existing shell variables still take precedence.")
        elif args.command == "gui":
            from .web import serve

            if args.env_file:
                load_environment(env_file=args.env_file)
            serve(
                args.workspace,
                port=args.port,
                public_url=args.public_url,
                nexus=args.nexus,
                iframe_origin=args.iframe_origin,
            )
        elif args.command == "init-config":
            with args.path.open("x") as stream:
                stream.write(files("gladius").joinpath("data/example.yaml").read_text())
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
            if args.command == "demo":
                if args.example == "mast-demo":
                    load_environment(Path.cwd(), env_file=args.env_file)
                    print(
                        "Querying MAST for one calibrated parent; full-image download follows selection."
                    )
                    path = create_mast_demo(
                        args.directory or Path("mast-demo"),
                        max_parent_mib=512 if args.max_parent_mib is None else args.max_parent_mib,
                    )
                    print(f"Configuration: {path}")
                else:
                    if args.directory is not None or args.max_parent_mib is not None:
                        raise ValueError("--directory and --max-parent-mib apply to demo mast-demo")
                    path = create_demo(Path(args.example))
                    load_environment(path.parent, env_file=args.env_file)
            else:
                path = args.config
                load_environment(path.expanduser().resolve().parent, env_file=args.env_file)
            manifest = run(load_config(path, targets_path=getattr(args, "targets", None)))
            print(f"Manifest: {manifest}")
            return 0 if json.loads(manifest.read_text())["status"] == "complete" else 1
    except (Exception, KeyboardInterrupt) as exc:
        print(f"gladius: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1
    return 0
