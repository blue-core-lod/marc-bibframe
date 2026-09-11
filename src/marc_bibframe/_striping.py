"""Coerce a BIBFRAME graph into striped RDF/XML descriptions.

bibframe2marc converts one "description" at a time, which LC's design notes
define as a graph holding exactly one top-level ``bf:Instance`` and zero or one
top-level ``bf:Work``, linked by ``bf:instanceOf`` or ``bf:hasInstance``, and
serialized as *striped* RDF/XML: property and class elements alternating, with
each object nested inside the property that reaches it.

rdflib's RDF/XML serializer does not produce that shape, so a graph that did
not come straight out of marc2bibframe2 has to be rebuilt here. This is the
job LC's Biblio::BF2MARC does in Perl.
"""

from __future__ import annotations

from collections import Counter

import lxml.etree as ET
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.collection import Collection
from rdflib.namespace import RDF, RDFS
from rdflib.term import Node

BF = "http://id.loc.gov/ontologies/bibframe/"
BFLC = "http://id.loc.gov/ontologies/bflc/"
MADSRDF = "http://www.loc.gov/mads/rdf/v1#"

INSTANCE = URIRef(f"{BF}Instance")
WORK = URIRef(f"{BF}Work")
INSTANCE_OF = URIRef(f"{BF}instanceOf")
HAS_INSTANCE = URIRef(f"{BF}hasInstance")

_RDF = str(RDF)
_ABOUT = f"{{{_RDF}}}about"
_RESOURCE = f"{{{_RDF}}}resource"
_NODE_ID = f"{{{_RDF}}}nodeID"
_DATATYPE = f"{{{_RDF}}}datatype"
_PARSE_TYPE = f"{{{_RDF}}}parseType"
_DESCRIPTION = f"{{{_RDF}}}Description"
_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

#: Prefixes marc2bibframe2 itself declares, so striped output reads the same.
_NSMAP = {
    "rdf": _RDF,
    "rdfs": str(RDFS),
    "bf": BF,
    "bflc": BFLC,
    "madsrdf": MADSRDF,
}

#: Namespaces whose classes are worth naming an element after, best first.
_CLASS_NAMESPACES = (BF, BFLC, MADSRDF)

#: When a node carries several types, marc2bibframe2 names the element after the
#: general class and leaves the specific ones as rdf:type children: a Hub that
#: is also an Arrangement is <bf:Hub>, an Agent that is also a Person is
#: <bf:Agent>. The rules key on the element name, so choosing the specific class
#: instead hides whole fields from them -- a bf:Arrangement element costs you the
#: 240. This ordering is read off the element/rdf:type pairings in LC's own test
#: descriptions (bibframe2marc rules/test/data); anything absent from it sorts
#: last, alphabetically, which at least stays put between runs.
_GENERAL_CLASSES = tuple(
    f"{namespace}{name}"
    for namespace, names in (
        (
            BF,
            (
                "Work",
                "Instance",
                "Hub",
                "Agent",
                "Title",
                "Contribution",
                "ProvisionActivity",
                "GenreForm",
                "Topic",
                "Place",
                "Note",
                "Role",
                "Media",
                "Content",
                "Language",
                "Temporal",
                "Organization",
                "Person",
                "SystemRequirement",
                "DescriptionAuthentication",
                "VariantTitle",
            ),
        ),
        (MADSRDF, ("Authority", "RWO", "PersonalName", "CorporateName")),
    )
    for name in names
)

#: How deep to nest before falling back to a bare reference. Descriptions are
#: nowhere near this deep; the limit is a backstop against a graph that leads
#: somewhere unexpected.
_MAX_DEPTH = 12


class NotADescription(ValueError):
    """The graph holds no bf:Instance, so there is no description to convert."""


def descriptions(graph: Graph) -> list[ET._Element]:
    """Every BIBFRAME description in a graph, as striped ``rdf:RDF`` documents.

    Ordered by Instance URI so that converting the same graph twice gives the
    same records in the same order.
    """
    instances = sorted(graph.subjects(RDF.type, INSTANCE, unique=True), key=str)
    if not instances:
        raise NotADescription(
            "no bf:Instance in the graph, so there is nothing to convert. "
            "bibframe2marc builds a MARC record around an Instance and the "
            "Work it is an instance of"
        )
    return [_Striper(graph, instance).description() for instance in instances]


class _Striper:
    """Builds the striped RDF/XML for one Instance and its Work."""

    def __init__(self, graph: Graph, instance: Node):
        self.graph = graph
        self.instance = instance
        self.work = self._work_for(instance)
        #: Neither of these is ever nested: the stylesheet wants them side by
        #: side at the top level, referring to each other.
        self.top = {node for node in (instance, self.work) if node is not None}
        #: Blank nodes more than one thing points at need an identifier, so the
        #: second reference can point at the first rather than copying it.
        counts = Counter(
            obj for obj in graph.objects(unique=False) if isinstance(obj, BNode)
        )
        self.shared = {node for node, count in counts.items() if count > 1}
        self.emitted: set[Node] = set()

    def _work_for(self, instance: Node) -> Node | None:
        work = self.graph.value(instance, INSTANCE_OF)
        if work is None:
            work = self.graph.value(predicate=HAS_INSTANCE, object=instance)
        if isinstance(work, Literal):  # a graph can say anything
            return None
        return work

    def description(self) -> ET._Element:
        document = ET.Element(f"{{{_RDF}}}RDF", nsmap=_NSMAP)
        # Work first, then Instance: the order marc2bibframe2 emits.
        if self.work is not None:
            document.append(self._node(self.work, (), WORK))
        document.append(self._node(self.instance, (), INSTANCE))
        return document

    def _node(
        self,
        node: Node,
        path: tuple[Node, ...],
        force_class: URIRef | None = None,
    ) -> ET._Element:
        """One class element, with its properties nested inside it."""
        classes = sorted(self.graph.objects(node, RDF.type, unique=True), key=str)
        named = force_class or self._class_element(classes)
        element = ET.Element(_qname(named) if named else _DESCRIPTION)

        if isinstance(node, URIRef):
            element.set(_ABOUT, str(node))
        else:
            self.emitted.add(node)
            if node in self.shared:
                element.set(_NODE_ID, str(node))

        for predicate, obj in self._properties(node, skip_type=named):
            element.append(self._property(predicate, obj, path + (node,)))
        return element

    def _class_element(self, classes: list[Node]) -> URIRef | None:
        """The class to name this element after, if any is suitable."""
        uris = [candidate for candidate in classes if isinstance(candidate, URIRef)]
        for namespace in _CLASS_NAMESPACES:
            candidates = [uri for uri in uris if str(uri).startswith(namespace)]
            if candidates:
                return min(candidates, key=_generality)
        return None

    def _properties(self, node, skip_type):
        """This node's statements, in a stable order, minus the named class.

        The class an element is named after is not repeated as an rdf:type
        child, but every other type is: the rules test both the element name
        and rdf:type/@rdf:resource.
        """
        statements = sorted(
            self.graph.predicate_objects(node),
            key=lambda pair: (str(pair[0]), str(pair[1])),
        )
        return [
            (predicate, obj)
            for predicate, obj in statements
            if not (predicate == RDF.type and obj == skip_type)
        ]

    def _property(self, predicate, obj, path) -> ET._Element:
        element = ET.Element(_qname(predicate))

        if self._is_collection(obj):
            # An ordered list, e.g. madsrdf:elementList. It has to go back out
            # as parseType="Collection": the rules read its members with paths
            # like madsrdf:elementList/madsrdf:NameElement, which an
            # rdf:first/rdf:rest chain would hide from them, and the order is
            # part of the data.
            element.set(_PARSE_TYPE, "Collection")
            for member in Collection(self.graph, obj):
                element.append(self._node(member, path))
            return element

        if isinstance(obj, Literal):
            element.text = str(obj)
            if obj.language:
                element.set(_LANG, obj.language)
            elif obj.datatype:
                element.set(_DATATYPE, str(obj.datatype))
            return element

        if self._nestable(obj, path):
            element.append(self._node(obj, path))
        elif isinstance(obj, BNode):
            # Only reachable for a shared or looping blank node, which the
            # first encounter gave an identifier to.
            element.set(_NODE_ID, str(obj))
        else:
            element.set(_RESOURCE, str(obj))
        return element

    def _is_collection(self, obj) -> bool:
        """Is this the head of an RDF list?"""
        return obj == RDF.nil or (obj, RDF.first, None) in self.graph

    def _nestable(self, obj, path) -> bool:
        if obj in self.top or obj in path or len(path) >= _MAX_DEPTH:
            return False
        if isinstance(obj, BNode) and obj in self.shared and obj in self.emitted:
            return False
        # Nothing to nest: no statements of its own, so a reference says it all.
        return any(True for _ in self.graph.predicate_objects(obj))


def _generality(uri: URIRef) -> tuple[int, str]:
    """Sort key putting the most general known class first."""
    try:
        return (_GENERAL_CLASSES.index(str(uri)), "")
    except ValueError:
        return (len(_GENERAL_CLASSES), str(uri))


def _qname(uri: URIRef) -> str:
    """``{namespace}local`` for lxml, split at the last # or /."""
    text = str(uri)
    for index in range(len(text) - 1, 0, -1):
        if text[index] in "#/":
            local = text[index + 1 :]
            if local:
                return f"{{{text[: index + 1]}}}{local}"
            break
    raise ValueError(f"cannot use {uri} as an XML element name")
