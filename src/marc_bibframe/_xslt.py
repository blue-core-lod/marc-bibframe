"""Plumbing shared by the two vendored Library of Congress stylesheets.

Neither stylesheet can be read out of the package as bytes: marc2bibframe2
``xsl:include``s some thirty siblings by relative href, and bibframe2marc's
compiler reads its rules by relative path. Both need a real directory on disk.
"""

from __future__ import annotations

import atexit
import functools
from contextlib import ExitStack
from importlib.resources import as_file, files
from pathlib import Path
from typing import Any

import lxml.etree as ET

#: Directory under this package that each vendored stylesheet lives in.
STYLESHEETS = {
    "marc2bibframe2": "xsl",
    "bibframe2marc": "bf2marc",
}

MARCXML_NS = "http://www.loc.gov/MARC21/slim"
COLLECTION_OPEN = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<collection xmlns="' + MARCXML_NS.encode() + b'">'
)
COLLECTION_CLOSE = b"</collection>"

# Holding the ExitStack open for the life of the process keeps the extracted
# directory around when the package is imported from a zip.
_files = ExitStack()
atexit.register(_files.close)


@functools.cache
def resource_dir(name: str) -> Path:
    """The real on-disk directory holding a vendored stylesheet."""
    return _files.enter_context(as_file(files(__package__).joinpath(name)))


def upstream(stylesheet: str = "marc2bibframe2") -> dict[str, str]:
    """The upstream repository, tag and commit vendored for a stylesheet.

    Defaults to marc2bibframe2, the MARC to BIBFRAME direction. Pass
    ``"bibframe2marc"`` for the reverse.
    """
    try:
        directory = STYLESHEETS[stylesheet]
    except KeyError:
        raise ValueError(
            f"unknown stylesheet {stylesheet!r}; "
            f"expected one of {', '.join(sorted(STYLESHEETS))}"
        ) from None
    text = (resource_dir(directory) / "UPSTREAM").read_text()
    return {
        k.strip(): v.strip()
        for k, _, v in (line.partition(":") for line in text.splitlines())
        if k
    }


def xslt_params(**kwargs: Any) -> dict[str, Any]:
    """Build XSLT parameters, dropping any left as None so the stylesheet default wins.

    Booleans become the XPath expressions true()/false() rather than string
    literals, because every non-empty string is true in XPath -- passing "false"
    as a string would quietly mean the opposite of what was asked for.
    """
    params = {}
    for name, value in kwargs.items():
        if value is None:
            continue
        params[name] = (
            "true()"
            if value is True
            else "false()"
            if value is False
            else ET.XSLT.strparam(str(value))
        )
    return params
