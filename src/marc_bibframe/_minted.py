"""Describe the headings MARC does not identify as blank nodes.

When a name, subject or genre/form heading has no URI in its $0 (or $1, or $w),
marc2bibframe2 mints one for it from ``baseuri`` and the record id, e.g.
``http://example.org/99123456#Topic650-6``, and hangs the heading's label,
source and marcKey off that URI. The URI names nothing, and a store that keeps
a Work's blank nodes inline but treats every URI as a reference to something
described elsewhere ends up with the URI and without the label.

:func:`blank_default_uris` turns those minted URIs back into blank nodes, so
the heading travels with the Work that cites it. Only the headings, and the
agent of a uniform-title Hub, are rewritten: the record's own ``#Work`` and
``#Instance``, the Hubs, the related
Works and Instances of the linking fields, and Items keep their URIs, because
they are resources a store may keep records of in their own right. A URI taken
from the MARC is never under ``{baseuri}{record id}#``, so it is left alone.
"""

from __future__ import annotations

import re

from rdflib import BNode, Graph, URIRef
from rdflib.term import Node

#: The fragment the stylesheet gives a heading it mints a URI for: a name the
#: stylesheet picks by tag (not the heading's rdf:type), the MARC tag (880 for
#: a linked field) and the field's position in the record, e.g. ``Agent100-4``
#: or ``Place651-9``. A uniform-title Hub's agent is the Hub's fragment with
#: ``-Agent`` on the end, e.g. ``Hub240-11-Agent``.
_HEADING_FRAGMENT = re.compile(
    r"(?:Agent|Topic|GenreForm|Event|Temporal|Place)\d{3}-\d+|Hub\d{3}-\d+-Agent"
)


def is_default_uri(node: Node, baseuri: str) -> bool:
    """Whether node is a URI the stylesheet minted for a heading.

    The stylesheet builds these as ``{baseuri}{record id}#{fragment}``, with the
    record id URL-encoded so that it cannot itself contain a ``#``.

    The match is on the fragment's name, not on the node's ``rdf:type``, and
    one name covers several classes:

    - ``Agent``: ``bf:Agent`` with ``bf:Person``, ``bf:Family``,
      ``bf:Organization``, ``bf:Jurisdiction`` or ``bf:Meeting`` (and
      ``bflc:Uncontrolled`` for a 720)
    - ``Topic``: ``bf:Topic``, with ``madsrdf:ComplexSubject`` if subdivided
    - ``Event``, ``Temporal``, ``Place`` and ``GenreForm``: ``bf:Event``,
      ``bf:Temporal``, ``bf:Place`` (with ``madsrdf:HierarchicalGeographic``
      for a 662) and ``bf:GenreForm``
    - ``Hub{tag}-{n}-Agent``: the ``bf:Agent`` of a 130, 240 or X30 Hub. The
      Hub itself (``Hub240-11``) keeps its URI

    A subdivided 647, 648, 651 or 655 keeps its own name but is typed
    ``bf:Topic`` and ``madsrdf:ComplexSubject``, and it still matches.
    """
    if not isinstance(node, URIRef) or not node.startswith(baseuri):
        return False
    _, hash_, fragment = node[len(baseuri) :].partition("#")
    return bool(hash_) and _HEADING_FRAGMENT.fullmatch(fragment) is not None


def blank_default_uris(graph: Graph, baseuri: str) -> Graph:
    """Replace each minted heading URI in graph with a blank node, in place.

    Every triple the URI took part in, as subject or object, is kept on the
    blank node that replaces it. A URI cited more than once becomes one blank
    node cited the same number of times. Returns graph.
    """
    blanks: dict[Node, BNode] = {}

    def swap(node: Node) -> Node:
        if is_default_uri(node, baseuri):
            return blanks.setdefault(node, BNode())
        return node

    for triple in list(graph):
        subject, predicate, obj = triple
        rewritten = (swap(subject), predicate, swap(obj))
        if rewritten != triple:
            graph.remove(triple)
            graph.add(rewritten)
    return graph
