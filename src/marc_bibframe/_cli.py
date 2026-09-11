"""Input and output plumbing shared by the two command line entry points."""

from __future__ import annotations

import sys
from pathlib import Path


def read_input(path: str, prog: str) -> bytes:
    """Read the named file, or standard input when it is ``-``."""
    if path == "-":
        data = sys.stdin.buffer.read()
    else:
        file = Path(path)
        if not file.exists():
            sys.exit(f"{prog}: {file}: no such file")
        data = file.read_bytes()

    if not data.strip():
        sys.exit(f"{prog}: no input")
    return data


def write_output(data: bytes, path: str | None) -> None:
    """Write to the named file, or standard output when there is none."""
    if path:
        Path(path).write_bytes(data)
    else:
        sys.stdout.buffer.write(data)
