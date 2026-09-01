"""Convert MARC records to BIBFRAME RDF.

A thin Python wrapper around the Library of Congress marc2bibframe2 XSLT
(https://github.com/lcnetdev/marc2bibframe2), which is vendored in this
package. See ``src/marc_bibframe/xsl/UPSTREAM`` for the version, and
``patches/`` for any local changes to it.
"""

from __future__ import annotations

import atexit
import functools
from contextlib import ExitStack
from importlib.resources import as_file, files
from io import BytesIO
from typing import Any, BinaryIO

import lxml.etree as ET
import pymarc
from pymarc.marcxml import record_to_xml
from rdflib import Graph

__all__ = [
    "DEFAULT_BASE_URI",
    "marc_to_graph",
    "marc_to_marcxml",
    "marcxml_to_graph",
    "marcxml_to_rdfxml",
    "upstream",
]

#: The stylesheet's own default. It is deliberately non-resolvable: URIs the
#: transform mints for entities that MARC does not identify (agents, topics,
#: the work and instance themselves) are built from it, and they name nothing.
DEFAULT_BASE_URI = "http://example.org/"

_MARCXML_NS = "http://www.loc.gov/MARC21/slim"
_COLLECTION_OPEN = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<collection xmlns="' + _MARCXML_NS.encode() + b'">'
)
_COLLECTION_CLOSE = b"</collection>"

# The stylesheet xsl:includes ~30 siblings by relative href, so it has to be
# resolved from a real directory rather than read out of the package as bytes.
# Holding the ExitStack open for the life of the process keeps that directory
# around when the package is imported from a zip.
_files = ExitStack()
atexit.register(_files.close)


@functools.cache
def _xsl_dir():
    return _files.enter_context(as_file(files(__package__).joinpath("xsl")))


@functools.cache
def _transform() -> ET.XSLT:
    """Parse and compile the stylesheet, once per process (it is not cheap)."""
    return ET.XSLT(ET.parse(str(_xsl_dir() / "marc2bibframe2.xsl")))


def upstream() -> dict[str, str]:
    """The upstream marc2bibframe2 repository, tag and commit that is vendored here."""
    text = (_xsl_dir() / "UPSTREAM").read_text()
    return {
        k.strip(): v.strip()
        for k, _, v in (line.partition(":") for line in text.splitlines())
        if k
    }


def _xslt_params(**kwargs: Any) -> dict[str, Any]:
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


def marc_to_marcxml(marc: bytes | BinaryIO) -> bytes:
    """Convert binary MARC21 to a MARCXML ``<collection>`` of one or more records."""
    handle = BytesIO(marc) if isinstance(marc, bytes) else marc
    parts = [_COLLECTION_OPEN]
    for i, record in enumerate(pymarc.MARCReader(handle)):
        if record is None:
            raise ValueError(f"Could not read MARC record at position {i}")
        parts.append(record_to_xml(record, namespace=False))
    parts.append(_COLLECTION_CLOSE)
    return b"".join(parts)


def marcxml_to_rdfxml(
    marcxml: str | bytes,
    *,
    baseuri: str = DEFAULT_BASE_URI,
    idfield: str | None = None,
    idsource: str | None = None,
    localfields: bool | None = None,
    bcp47_inference: bool | None = None,
    generation_datestamp: str | None = None,
) -> bytes:
    """Transform MARCXML into BIBFRAME RDF/XML.

    Accepts a single ``<record>`` or a ``<collection>`` of them.

    baseuri
        Base for the URIs the transform mints. Every minted URI has the form
        ``{baseuri}{record id}#{fragment}``, so they are scoped to the record
        they came from and are not authority URIs -- two records describing the
        same person yield two different agent URIs. Reconciling them against an
        authority is the caller's job.
    idfield
        MARC field holding the record id, ``001`` by default. Suffix a subfield
        code to use one, e.g. ``035a``.
    idsource
        URI identifying the source of the record id, e.g.
        ``http://id.loc.gov/vocabulary/organizations/dlc``.
    localfields
        Convert fields LC defines locally (e.g. 859), off by default.
    bcp47_inference
        Omit a BCP-47 script subtag when it can be inferred from the language.
    generation_datestamp
        Override the timestamp recorded in the work's admin metadata. Set it to
        make output byte-for-byte reproducible.
    """
    if isinstance(marcxml, str):
        # Encode first: lxml refuses a str carrying an encoding declaration.
        marcxml = marcxml.encode("utf-8")
    params = _xslt_params(
        baseuri=baseuri,
        idfield=idfield,
        idsource=idsource,
        localfields=localfields,
        bcp47inferrence=bcp47_inference,
        pGenerationDatestamp=generation_datestamp,
    )
    # lxml-stubs types XSLT's keyword parameters as bool; they are XSLT params.
    result = _transform()(ET.fromstring(marcxml), **params)  # type: ignore[arg-type]
    return ET.tostring(
        result, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )


def marcxml_to_graph(marcxml: str | bytes, **kwargs: Any) -> Graph:
    """Transform MARCXML into BIBFRAME as an rdflib Graph.

    Takes the same keyword arguments as :func:`marcxml_to_rdfxml`.
    """
    graph = Graph()
    graph.parse(data=marcxml_to_rdfxml(marcxml, **kwargs), format="xml")
    return graph


def marc_to_graph(marc: bytes | BinaryIO, **kwargs: Any) -> Graph:
    """Convert binary MARC21 straight to BIBFRAME as an rdflib Graph.

    Takes the same keyword arguments as :func:`marcxml_to_rdfxml`.
    """
    return marcxml_to_graph(marc_to_marcxml(marc), **kwargs)
