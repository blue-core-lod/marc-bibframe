"""Headings without a $0 come out as blank nodes, not minted URIs.

https://github.com/blue-core-lod/marc-bibframe/issues/11
"""

import pytest
from rdflib import RDF, RDFS, BNode, Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic

from marc_bibframe import DEFAULT_BASE_URI, marcxml_to_graph, marcxml_to_jsonld
from marc_bibframe._minted import blank_default_uris, is_default_uri
from marc_bibframe.cli import main

from .conftest import FIXTURES

BF = Namespace("http://id.loc.gov/ontologies/bibframe/")
RECORD = f"{DEFAULT_BASE_URI}in00000125067"
HEADINGS_XML = str(FIXTURES / "headings.xml")
STAMP = "2026-09-01T00:00:00"


@pytest.fixture
def headings_marcxml() -> str:
    return (FIXTURES / "headings.xml").read_text()


@pytest.fixture
def graph(headings_marcxml) -> Graph:
    return marcxml_to_graph(headings_marcxml)


def minted(graph: Graph) -> set[str]:
    """The fragments of the record-scoped URIs left in graph."""
    return {
        node.split("#", 1)[1]
        for triple in graph
        for node in triple
        if isinstance(node, URIRef) and node.startswith(f"{RECORD}#")
    }


def work(graph: Graph) -> URIRef:
    node = graph.value(predicate=RDF.type, object=BF.Monograph)
    assert isinstance(node, URIRef)
    return node


def heading(graph: Graph, predicate: URIRef, label: str) -> BNode:
    """The value of predicate on the Work that carries label."""
    for node in graph.objects(work(graph), predicate):
        if (node, RDFS.label, Literal(label)) in graph:
            assert isinstance(node, BNode)
            return node
    raise AssertionError(f"no {predicate} labelled {label!r}")


def test_only_the_work_instance_and_hubs_keep_minted_uris(graph):
    assert minted(graph) == {"Work", "Instance", "Hub240-11", "Hub240-11-Agent"}


@pytest.mark.parametrize(
    ("predicate", "label", "class_", "source"),
    [
        (
            BF.subject,
            "Imaginary wars and battles",
            BF.Topic,
            "http://id.loc.gov/vocabulary/subjectSchemes/fast",
        ),
        (
            BF.subject,
            "Guerres et batailles imaginaires--Romans, nouvelles, etc.",
            BF.Topic,
            "http://id.loc.gov/vocabulary/subjectSchemes/rvm",
        ),
        (
            BF.genreForm,
            "Space operas (Romans)",
            BF.GenreForm,
            "http://id.loc.gov/vocabulary/genreFormSchemes/rvmgf",
        ),
        (BF.subject, "Siege of the Last Station (2423)", BF.Event, None),
        (BF.subject, "2400-2499", BF.Temporal, None),
        (BF.subject, "United States--California--Los Angeles.", BF.Place, None),
    ],
)
def test_headings_are_blank_nodes_that_keep_their_description(
    graph, predicate, label, class_, source
):
    node = heading(graph, predicate, label)
    assert (node, RDF.type, class_) in graph
    if source is not None:
        assert (node, BF.source, URIRef(source)) in graph


def test_agents_are_blank_nodes_that_keep_their_marckey(graph):
    agents = [
        graph.value(contribution, BF.agent)
        for contribution in graph.objects(work(graph), BF.contribution)
    ]
    assert agents
    assert all(isinstance(agent, BNode) for agent in agents)
    labels = {str(graph.value(agent, RDFS.label)) for agent in agents}
    assert labels == {"Argus (Science fiction writer)", "Alice, (Fictitious character)"}
    assert all(
        graph.value(agent, URIRef("http://id.loc.gov/ontologies/bflc/marcKey"))
        for agent in agents
    )


def test_a_heading_with_a_0_keeps_its_uri(graph):
    cats = URIRef("http://id.loc.gov/authorities/subjects/sh85021262")
    assert (work(graph), BF.subject, cats) in graph


def test_blanking_loses_no_triples(headings_marcxml):
    """The default graph is the minted one with each heading URI renamed."""
    kept = marcxml_to_graph(
        headings_marcxml, mint_default_uris=True, generation_datestamp=STAMP
    )
    blanked = marcxml_to_graph(headings_marcxml, generation_datestamp=STAMP)
    assert isomorphic(blank_default_uris(kept, DEFAULT_BASE_URI), blanked)


def test_mint_default_uris_keeps_the_stylesheet_uris(headings_marcxml):
    graph = marcxml_to_graph(headings_marcxml, mint_default_uris=True)
    assert {
        "Agent100-10",
        "Agent700-37",
        "Topic650-22",
        "GenreForm655-30",
        "Event647-20",
        "Temporal648-21",
        "Place651-29",
        "Place662-36",
    } <= minted(graph)


def test_follows_the_baseuri_in_use(headings_marcxml):
    graph = marcxml_to_graph(headings_marcxml, baseuri="https://example.edu/c/")
    left = {
        str(node)
        for triple in graph
        for node in triple
        if isinstance(node, URIRef) and node.startswith("https://example.edu/c/")
    }
    assert {uri.split("#", 1)[1] for uri in left} == {
        "Work",
        "Instance",
        "Hub240-11",
        "Hub240-11-Agent",
    }


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("http://id.loc.gov/resources99123456#Topic650-6", True),
        ("http://id.loc.gov/resources99123456#Agent880-2", True),
        # A $0 under the same base has no record id and fragment of that shape
        ("http://id.loc.gov/resources/works/123456", False),
        ("http://id.loc.gov/resources99123456#Work", False),
        ("http://id.loc.gov/resources99123456#Hub240-6", False),
        ("http://id.loc.gov/resources99123456#Topic650-6-Agent", False),
        ("http://id.loc.gov/authorities/subjects/sh85021262", False),
    ],
)
def test_is_default_uri(uri, expected):
    """The marc2bf DAG passes a baseuri without a trailing slash."""
    assert is_default_uri(URIRef(uri), "http://id.loc.gov/resources") is expected


def test_jsonld_has_no_minted_heading_uris(headings_marcxml):
    document = marcxml_to_jsonld(headings_marcxml).decode()
    assert f"{RECORD}#Topic" not in document
    assert f"{RECORD}#Agent100" not in document
    assert "Imaginary wars and battles--Fiction" in document


def test_cli_mint_default_uris(capsys):
    assert main([HEADINGS_XML, "-f", "nt"]) == 0
    assert f"<{RECORD}#Topic650-22>" not in capsys.readouterr().out
    assert main([HEADINGS_XML, "-f", "nt", "--mint-default-uris"]) == 0
    assert f"<{RECORD}#Topic650-22>" in capsys.readouterr().out
