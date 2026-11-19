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
from rdflib import BNode, Graph, URIRef
from rdflib.term import Node

from marc_bibframe._jsonld import bounded_document, dumps
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
    "marc_to_jsonld",
    "marc_to_marcxml",
    "marcxml_to_graph",
    "marcxml_to_jsonld",
    "marcxml_to_rdfxml",
    "upstream",
]

#: URIs the transform mints for entities that MARC does not identify (agents,
#: topics, the work and instance themselves) are built from this, and they name
#: nothing. So it is a URN, which cannot be mistaken for a URI that resolves the
#: way the stylesheet's own ``http://example.org/`` can.
DEFAULT_BASE_URI = "urn:x-marc-bibframe:"


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


def marcxml_to_graph(
    marcxml: str | bytes, *, blank_nodes: bool = False, **kwargs: Any
) -> Graph:
    """Transform MARCXML into BIBFRAME as an rdflib Graph.

    Takes the keyword arguments of :func:`marcxml_to_rdfxml`, and one more:

    blank_nodes
        Describe every resource MARC does not identify -- the Work and
        Instance, Hubs, Items, and headings with no URI in their $0 -- as a
        blank node rather than by the URI minted for it, which names nothing.
        For a store that mints its own URIs, as Blue Core does for a blank
        Work or Instance. The URIs are found by the default ``baseuri``, so
        passing any other raises ValueError.

        Serialize such a graph as N-Triples or RDF/XML: before rdflib 8, its
        JSON-LD writer drops a blank Work and Instance
        (https://github.com/RDFLib/rdflib/pull/3679), and its Turtle writer
        can write a list cell twice
        (https://github.com/RDFLib/rdflib/issues/3736). Nor can it go back to
        MARC, since bibframe2marc links the Work and Instance by URI.
    """
    baseuri = kwargs.get("baseuri", DEFAULT_BASE_URI)
    if blank_nodes and baseuri != DEFAULT_BASE_URI:
        raise ValueError(
            f"baseuri={baseuri!r} cannot be used with blank_nodes, which finds "
            f"the minted URIs by the default base, {DEFAULT_BASE_URI}"
        )
    graph = Graph()
    graph.parse(data=marcxml_to_rdfxml(marcxml, **kwargs), format="xml")
    if blank_nodes:
        _blank_minted_uris(graph)
    return graph


def _blank_minted_uris(graph: Graph) -> None:
    """Replace each URI under DEFAULT_BASE_URI with a blank node, in place.

    Every triple the URI took part in, as subject or object, is kept on the
    blank node that replaces it, and a URI cited more than once becomes one
    blank node cited the same number of times.
    """
    blanks: dict[Node, BNode] = {}

    def swap(node: Node) -> Node:
        if isinstance(node, URIRef) and node.startswith(DEFAULT_BASE_URI):
            return blanks.setdefault(node, BNode())
        return node

    for triple in list(graph):
        subject, predicate, obj = triple
        rewritten = (swap(subject), predicate, swap(obj))
        if rewritten != triple:
            graph.remove(triple)
            graph.add(rewritten)


def marc_to_graph(marc: bytes | BinaryIO, **kwargs: Any) -> Graph:
    """Convert binary MARC21 straight to BIBFRAME as an rdflib Graph.

    Takes the same keyword arguments as :func:`marcxml_to_graph`.
    """
    return marcxml_to_graph(marc_to_marcxml(marc), **kwargs)


def marcxml_to_jsonld(marcxml: str | bytes, **kwargs: Any) -> bytes:
    """Transform MARCXML into BIBFRAME as a bibframe-json document.

    Takes the same keyword arguments as :func:`marcxml_to_graph`.

    These bytes are the *bounded description* that
    https://bibframe-json.org defines: the document is the ``bf:Instance``, the
    Work it instantiates is embedded where ``instanceOf`` reaches it, every
    property is an array so a reader can loop without checking, and the context
    is named rather than inlined. A MARCXML ``<collection>`` holds several
    records, so the result is then a ``@graph`` of Instance documents, in
    Instance order.

    This is what the command line writes for ``--format json-ld``. For
    rdflib's own flat array of expanded nodes, serialize the graph yourself:
    ``marcxml_to_graph(...).serialize(format="json-ld")``.

    Raises ValueError for ``blank_nodes=True``: a bounded description needs an
    ``@id`` on the Instance and the Work. Serialize
    ``marcxml_to_graph(..., blank_nodes=True)`` as N-Triples or RDF/XML
    instead.
    """
    if kwargs.get("blank_nodes"):
        raise ValueError(
            "blank_nodes cannot make a bounded description, which needs an @id "
            "on the Instance and the Work; serialize "
            "marcxml_to_graph(..., blank_nodes=True) as N-Triples or RDF/XML "
            "instead"
        )
    return dumps(bounded_document(marcxml_to_graph(marcxml, **kwargs)))


def marc_to_jsonld(marc: bytes | BinaryIO, **kwargs: Any) -> bytes:
    """Convert binary MARC21 straight to a bibframe-json document.

    Takes the same keyword arguments as :func:`marcxml_to_graph`.
    """
    return marcxml_to_jsonld(marc_to_marcxml(marc), **kwargs)
