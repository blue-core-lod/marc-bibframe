"""Convert between MARC and BIBFRAME RDF.

A thin Python wrapper around two Library of Congress stylesheets, both vendored
in this package: marc2bibframe2 (https://github.com/lcnetdev/marc2bibframe2)
for MARC to BIBFRAME, and bibframe2marc
(https://github.com/lcnetdev/bibframe2marc) for the reverse. See the
``UPSTREAM`` file beside each for its version, and ``patches/`` for any local
changes to them.
"""

from __future__ import annotations

import functools
from io import BytesIO
from typing import Any, BinaryIO

import lxml.etree as ET
import pymarc
from pymarc.marcxml import record_to_xml
from rdflib import Graph

from marc_bibframe._xslt import (
    COLLECTION_CLOSE,
    COLLECTION_OPEN,
    resource_dir,
    upstream,
    xslt_params,
)
from marc_bibframe.bibframe_marc import (
    DEFAULT_USER_AGENT,
    FORMATS,
    AuthorityLookupWarning,
    bibframe_to_marc,
    bibframe_to_marcxml,
    clear_authority_cache,
)

__all__ = [
    "DEFAULT_BASE_URI",
    "DEFAULT_USER_AGENT",
    "FORMATS",
    "AuthorityLookupWarning",
    "bibframe_to_marc",
    "bibframe_to_marcxml",
    "clear_authority_cache",
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


@functools.cache
def _transform() -> ET.XSLT:
    """Parse and compile the stylesheet, once per process (it is not cheap)."""
    return ET.XSLT(ET.parse(str(resource_dir("xsl") / "marc2bibframe2.xsl")))


def marc_to_marcxml(marc: bytes | BinaryIO) -> bytes:
    """Convert binary MARC21 to a MARCXML ``<collection>`` of one or more records."""
    handle = BytesIO(marc) if isinstance(marc, bytes) else marc
    parts = [COLLECTION_OPEN]
    for i, record in enumerate(pymarc.MARCReader(handle)):
        if record is None:
            raise ValueError(f"Could not read MARC record at position {i}")
        parts.append(record_to_xml(record, namespace=False))
    parts.append(COLLECTION_CLOSE)
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
        Override the timestamp recorded in the work's admin metadata, which
        otherwise defaults to now. Set it to make the RDF/XML this function
        returns byte-for-byte reproducible. Note that a Graph serialized by
        rdflib still varies between runs, because rdflib mints fresh blank
        node labels each time.
    """
    if isinstance(marcxml, str):
        # Encode first: lxml refuses a str carrying an encoding declaration.
        marcxml = marcxml.encode("utf-8")
    params = xslt_params(
        baseuri=baseuri,
        idfield=idfield,
        idsource=idsource,
        localfields=localfields,
        bcp47inferrence=bcp47_inference,
        pGenerationDatestamp=generation_datestamp,
    )
    result = _transform()(ET.fromstring(marcxml), **params)
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
