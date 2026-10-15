"""Produce and read the bibframe-json JSON shape.

A BIBFRAME graph has no natural JSON expression. rdflib's is a flat array of
expanded nodes -- full property URIs as keys, no nesting, one object per
resource -- and LC's own ``.bounded.jsonld`` is the same. Neither is much use
to a reader who does not already know BIBFRAME inside out.

The ``bibframe-json`` package (https://bibframe-json.org) defines an opinionated
shape instead, and this module produces it. The document *is* the
``bf:Instance``: the Work it is an instance of is embedded where ``instanceOf``
reaches it, every property is an array so a reader can loop without checking,
the context is named rather than inlined, and a blank node carries no ``@id``.
A graph holding several Instances becomes a ``@graph`` of them.

Framing does the embedding and the compaction. The other three steps -- every
property an array, no blank-node ids, the context named -- are things framing
will not do for you, and all four are ported from bibframe-json's published
``example/produce.py``, which exists to be copied. The context and the schemas
come from the ``bibframe-json`` package, which also ships an offline loader so
that naming the context URL costs no network.
"""

from __future__ import annotations

import json
from typing import Any

import bibframe_json
from pyld import jsonld
from rdflib import Graph, URIRef
from rdflib.namespace import RDF

_BF = "http://id.loc.gov/ontologies/bibframe/"
_INSTANCE = URIRef(f"{_BF}Instance")

#: Keywords that hold one value by definition, so the array rule does not reach
#: them. ``@context`` is a vocabulary rather than data; ``@id`` is one
#: identifier.
_SINGULAR = ("@context", "@id", "@value", "@language", "@direction", "@index")


def _as_arrays(node: Any) -> Any:
    """Every property an array, which the context cannot promise on its own.

    ``@container: @set`` covers the terms the context declares and nothing
    else, so a property it has never heard of -- ``bflc:catalogerId`` and
    Sinopia's ``hasResourceTemplate`` are both real -- compacts to a bare
    value. The schema checks for an array, so coerce after framing.

    ``@type`` is the exception that proves the rule twice: on a node it is a
    list of classes and gets wrapped, on a value object it is one datatype IRI
    and must not be. ``@value`` is what tells them apart.
    """
    if isinstance(node, list):
        return [_as_arrays(item) for item in node]
    if not isinstance(node, dict):
        return node
    literal = "@value" in node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _SINGULAR:
            out[key] = value
        elif key == "@type":
            out[key] = value if literal or isinstance(value, list) else [value]
        else:
            listed = value if isinstance(value, list) else [value]
            out[key] = [_as_arrays(item) for item in listed]
    return out


def _without_blank_ids(node: Any) -> Any:
    """Drop the ``@id`` a processor invents for a node that has none.

    Framing labels every blank node ``_:b0``, ``_:b1`` and so on, because the
    same node could in principle be reached from more than one place. Those
    labels address nothing outside the document they appear in, so keeping them
    makes two identical values distinguishable by accident -- which is why the
    shape says a blank node carries no ``@id``.
    """
    if isinstance(node, list):
        return [_without_blank_ids(item) for item in node]
    if not isinstance(node, dict):
        return node
    return {
        key: _without_blank_ids(value)
        for key, value in node.items()
        if not (key == "@id" and isinstance(value, str) and value.startswith("_:"))
    }


def _expanded(graph: Graph) -> Any:
    """The graph as expanded JSON-LD, the form framing reads.

    N-Triples rather than N-Quads: rdflib only writes N-Quads for a
    context-aware store, and there are no named graphs here for it to lose.
    """
    return jsonld.from_rdf(graph.serialize(format="nt"))


def bounded_document(graph: Graph) -> dict[str, Any]:
    """The graph as a bibframe-json bounded description.

    Rooted at the ``bf:Instance``. One Instance gives the document itself;
    several give a ``@graph`` of them, in Instance order so that framing the
    same graph twice gives the same document.

    Raises ValueError if there is no ``bf:Instance``: a bounded description
    explains an Instance, so there is nothing to describe without one.
    """
    if not any(True for _ in graph.subjects(RDF.type, _INSTANCE)):
        raise ValueError(
            "no bf:Instance in the graph, so there is no bounded description "
            "to produce: one is about an Instance and the Work it instantiates"
        )

    framed = jsonld.frame(
        _expanded(graph),
        {
            "@context": bibframe_json.context()["@context"],
            "@type": str(_INSTANCE),
            # Describe a resource the first time it is reached and reference it
            # after, which is what keeps the description finite; and leave out
            # the properties the frame names but the record lacks, rather than
            # filling them with null.
            "@embed": "@once",
            "@omitDefault": True,
        },
    )
    document = _without_blank_ids(_as_arrays(framed))

    # Name the context rather than carrying the copy framing returns: inlined,
    # it is most of the document and says nothing about the record.
    document["@context"] = bibframe_json.CONTEXT_URL
    if "@graph" in document:
        document["@graph"].sort(key=lambda node: node.get("@id", ""))
    return document


def dumps(document: dict[str, Any]) -> bytes:
    """A bounded document as UTF-8 JSON, indented for reading.

    Not ASCII-escaped: BIBFRAME is full of non-Latin script, and escaping it
    makes a readable format unreadable for no gain.
    """
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def local_context(data: bytes) -> tuple[bytes, dict[str, Any] | None]:
    """Separate a document from a context we ship, so reading it costs no network.

    rdflib fetches a remote ``@context`` while parsing, and pyld while framing.
    When the document names a context that ``bibframe-json`` ships, hand it
    back for the parse to use and drop the URL, which is bibframe-json's own
    recipe. Anything else comes back untouched, URL and all.
    """
    try:
        document = json.loads(data)
    except ValueError:
        return data, None
    if not isinstance(document, dict):
        return data, None

    url = document.get("@context")
    context = bibframe_json.context_for(url) if isinstance(url, str) else None
    if context is None:
        return data, None

    del document["@context"]
    return json.dumps(document).encode("utf-8"), context
