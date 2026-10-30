"""Explicit local environment loading for command-line and GUI startup."""

from pathlib import Path

from dotenv import load_dotenv


def load_environment(directory: Path | str | None = None) -> bool:
    """Load only this directory's .env, preserving existing environment values.

    Python callers can opt in explicitly. No ancestor search, shell execution or
    variable interpolation is performed, and values are never logged.
    """
    directory = Path.cwd() if directory is None else Path(directory).expanduser()
    return load_dotenv(directory / ".env", override=False, interpolate=False)
