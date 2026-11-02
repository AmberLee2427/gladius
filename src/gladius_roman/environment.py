"""Explicit local environment loading for command-line and GUI startup."""

import os
from pathlib import Path

from dotenv import load_dotenv, set_key


def load_environment(
    directory: Path | str | None = None, *, env_file: Path | str | None = None
) -> bool:
    """Load this directory's .env or an explicit env_file, preserving shell values.

    Python callers can opt in explicitly. No ancestor search, shell execution or
    variable interpolation is performed, and values are never logged.
    """
    if env_file is not None:
        path = Path(env_file).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Environment file does not exist: {path}")
    else:
        directory = Path.cwd() if directory is None else Path(directory).expanduser()
        path = directory / ".env"
    return load_dotenv(path, override=False, interpolate=False)


def save_mast_token(token: str, env_file: Path | str = ".env") -> Path:
    """Update only MAST_API_TOKEN in a private dotenv file; never log its value."""
    path = Path(env_file).expanduser().absolute()
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("The environment destination must be a regular file, not a symlink")
    token = token.strip()
    if not token or any(character.isspace() or not character.isprintable() for character in token):
        raise ValueError(
            "The token must be nonempty and contain no whitespace or control characters"
        )
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
    if os.name != "nt":
        path.chmod(0o600)
    set_key(path, "MAST_API_TOKEN", token, quote_mode="always")
    if os.name != "nt":
        path.chmod(0o600)
    return path
