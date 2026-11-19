"""blank_nodes: the resources MARC does not identify, as blank nodes.

The stylesheet mints every URI under DEFAULT_BASE_URI, so with the option on
none of them should survive, and nothing they described should be lost.
"""

import pytest
from rdflib import RDF, RDFS, BNode, Graph, Namespace, URIRef
from rdflib.compare import isomorphic

from marc_bibframe import DEFAULT_BASE_URI, marc_to_graph, marcxml_to_graph

BF = Namespace("http://id.loc.gov/ontologies/bibframe/")
BFLC = Namespace("http://id.loc.gov/ontologies/bflc/")

#: Pinned so two conversions of the same record are comparable at all.
STAMP = "2026-09-01T00:00:00"


def blank(marcxml, **kwargs) -> Graph:
    return marcxml_to_graph(
        marcxml, blank_nodes=True, generation_datestamp=STAMP, **kwargs
    )


def labelled(graph: Graph, text: str) -> list:
    return [s for s, o in graph.subject_objects(RDFS.label) if text in str(o)]


def test_no_minted_uri_survives(headings_marcxml):
    minted = [
        node
        for node in blank(headings_marcxml).all_nodes()
        if isinstance(node, URIRef) and node.startswith(DEFAULT_BASE_URI)
    ]
    assert minted == []


def test_work_and_instance_are_blank(headings_marcxml):
    graph = blank(headings_marcxml)
    works = set(graph.subjects(RDF.type, BF.Work))
    instances = list(graph.subjects(RDF.type, BF.Instance))

    assert works and all(isinstance(work, BNode) for work in works)
    assert len(instances) == 1 and isinstance(instances[0], BNode)
    assert graph.value(instances[0], BF.instanceOf) in works


def test_headings_keep_their_description(headings_marcxml):
    graph = blank(headings_marcxml)
    topics = labelled(graph, "Imaginary wars and battles")
    assert topics and all(isinstance(topic, BNode) for topic in topics)

    # The 100, and the agent the stylesheet gives the 240 Hub
    people = [p for p in labelled(graph, "Argus") if (p, RDF.type, BF.Person) in graph]
    assert len(people) == 2
    assert all(isinstance(person, BNode) for person in people)
    assert all(graph.value(person, BFLC.marcKey) is not None for person in people)


def test_a_heading_with_an_id_keeps_it(headings_marcxml):
    cats = URIRef("http://id.loc.gov/authorities/subjects/sh85021262")
    assert cats in set(blank(headings_marcxml).all_nodes())


def test_no_triples_are_lost(headings_marcxml):
    minted = marcxml_to_graph(headings_marcxml, generation_datestamp=STAMP)
    assert len(blank(headings_marcxml)) == len(minted)


def test_runs_are_isomorphic(headings_marcxml):
    assert isomorphic(blank(headings_marcxml), blank(headings_marcxml))


def test_each_record_keeps_its_own_work(two_record_marcxml):
    graph = blank(two_record_marcxml)
    instances = list(graph.subjects(RDF.type, BF.Instance))
    works = {graph.value(instance, BF.instanceOf) for instance in instances}

    assert len(instances) == 2
    assert len(works) == 2
    assert all(isinstance(work, BNode) for work in works)


def test_binary_marc(verne_marc):
    graph = marc_to_graph(verne_marc, blank_nodes=True)
    instances = list(graph.subjects(RDF.type, BF.Instance))
    assert len(instances) == 1 and isinstance(instances[0], BNode)


@pytest.mark.parametrize("baseuri", ["https://example.edu/c/", None])
def test_a_baseuri_is_refused(verne_marcxml, baseuri):
    """None too: the stylesheet would fall back to its own base, unblanked."""
    with pytest.raises(ValueError, match="blank_nodes"):
        blank(verne_marcxml, baseuri=baseuri)


def test_the_default_baseuri_is_allowed(verne_marcxml):
    blank(verne_marcxml, baseuri=DEFAULT_BASE_URI)


def test_minting_is_still_the_default(verne_marcxml):
    graph = marcxml_to_graph(verne_marcxml)
    instance = URIRef("urn:x-marc-bibframe:99123456#Instance")
    assert (instance, RDF.type, BF.Instance) in graph
