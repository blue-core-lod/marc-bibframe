import pytest
from rdflib import RDF, RDFS, Graph, Literal, Namespace, URIRef

from marc_bibframe import (
    DEFAULT_BASE_URI,
    marc_to_graph,
    marc_to_marcxml,
    marcxml_to_graph,
    marcxml_to_rdfxml,
    upstream,
)

BF = Namespace("http://id.loc.gov/ontologies/bibframe/")
BFLC = Namespace("http://id.loc.gov/ontologies/bflc/")

VERNE = "Verne, Jules, 1828-1905"


def agent(graph: Graph) -> URIRef:
    """The one bf:Person in the graph."""
    people = list(graph.subjects(RDF.type, BF.Person))
    assert len(people) == 1
    person = people[0]
    assert isinstance(person, URIRef)
    return person


def test_marc_to_marcxml(verne_marc):
    marcxml = marc_to_marcxml(verne_marc)
    assert marcxml.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
    assert b'xmlns="http://www.loc.gov/MARC21/slim"' in marcxml
    assert marcxml.count(b"<record>") == 1
    assert b"Verne, Jules," in marcxml


def test_marc_to_marcxml_accepts_a_file_handle(verne_marc, tmp_path):
    path = tmp_path / "verne.mrc"
    path.write_bytes(verne_marc)
    with path.open("rb") as fh:
        assert marc_to_marcxml(fh) == marc_to_marcxml(verne_marc)


def test_marc_to_marcxml_handles_multiple_records(verne_marc):
    marcxml = marc_to_marcxml(verne_marc * 3)
    assert marcxml.count(b"<record>") == 3


def test_marcxml_to_rdfxml_returns_bytes(verne_marcxml):
    rdfxml = marcxml_to_rdfxml(verne_marcxml)
    assert isinstance(rdfxml, bytes)
    assert b"<rdf:RDF" in rdfxml


def test_marcxml_accepts_str_bytes_and_xml_declaration(verne_marcxml):
    """lxml rejects a str carrying an encoding declaration, so we encode first."""
    assert verne_marcxml.startswith("<?xml")
    # Pin the datestamp: the transform stamps the current time into the work's
    # admin metadata, so two unpinned calls differ whenever they straddle a
    # second, which is a coin flip rather than a bug in the encoding handling
    # this test is about.
    stamp = "2026-09-01T00:00:00"
    from_str = marcxml_to_rdfxml(verne_marcxml, generation_datestamp=stamp)
    from_bytes = marcxml_to_rdfxml(
        verne_marcxml.encode("utf-8"), generation_datestamp=stamp
    )
    assert from_str == from_bytes


def test_marcxml_to_graph(verne_marcxml):
    graph = marcxml_to_graph(verne_marcxml)
    assert len(graph) > 0
    assert (agent(graph), RDFS.label, Literal(VERNE)) in graph


def test_marc_to_graph_matches_the_two_step_route(verne_marc, verne_marcxml):
    """marc_to_graph is just marc_to_marcxml piped into marcxml_to_graph."""
    direct = marc_to_graph(verne_marc)
    stepwise = marcxml_to_graph(verne_marcxml)
    assert len(direct) == len(stepwise)
    assert (agent(direct), RDFS.label, Literal(VERNE)) in stepwise


def test_baseuri_is_used_for_minted_uris(verne_marcxml):
    graph = marcxml_to_graph(verne_marcxml, baseuri="https://example.edu/catalog/")
    assert str(agent(graph)).startswith("https://example.edu/catalog/99123456#")


def test_baseuri_defaults_to_the_stylesheet_default(verne_marcxml):
    graph = marcxml_to_graph(verne_marcxml)
    assert str(agent(graph)).startswith(DEFAULT_BASE_URI)


def test_minted_uris_are_scoped_to_the_record(verne_marcxml):
    """The same person in two records gets two URIs -- see the README."""
    other = verne_marcxml.replace("99123456", "99999999")
    assert agent(marcxml_to_graph(verne_marcxml)) != agent(marcxml_to_graph(other))


def test_agent_carries_a_marckey_for_reconciling(verne_marcxml):
    """The marcKey keeps subfield structure the flattened rdfs:label loses."""
    graph = marcxml_to_graph(verne_marcxml)
    marc_key = graph.value(agent(graph), BFLC.marcKey)
    assert str(marc_key) == "1001 $aVerne, Jules,$d1828-1905."


def test_idfield_selects_the_record_id(verne_marcxml):
    """Point at a subfield of another field and the minted URIs follow it."""
    tagged = verne_marcxml.replace(
        '<datafield tag="100"',
        '<datafield tag="035" ind1=" " ind2=" ">'
        '<subfield code="a">(OCoLC)ocm12345</subfield>'
        '</datafield><datafield tag="100"',
    )
    graph = marcxml_to_graph(tagged, idfield="035a")
    assert "OCoLC" in str(agent(graph))


def test_generation_datestamp_makes_output_reproducible(verne_marcxml):
    stamp = "2026-09-01T00:00:00"
    first = marcxml_to_rdfxml(verne_marcxml, generation_datestamp=stamp)
    second = marcxml_to_rdfxml(verne_marcxml, generation_datestamp=stamp)

    assert first == second
    assert stamp.encode() in first


def test_boolean_params_are_passed_as_xpath_not_strings(verne_marcxml):
    """A string "false" is true in XPath, so booleans need true()/false()."""
    on = marcxml_to_rdfxml(verne_marcxml, localfields=True)
    off = marcxml_to_rdfxml(verne_marcxml, localfields=False)
    assert b"<rdf:RDF" in on and b"<rdf:RDF" in off


def test_bcp47_script_is_not_inferred_when_no_script_was_found(russian_marcxml):
    """Regression test for patches/0001-bcp47-require-nonempty-script.patch.

    Pristine v3.1.0 emits the malformed tag "ru-" for this record.
    """
    rdfxml = marcxml_to_rdfxml(russian_marcxml)
    assert b'xml:lang="ru-"' not in rdfxml
    assert b'xml:lang="ru"' in rdfxml


def test_upstream_records_what_is_vendored():
    info = upstream()
    assert info["repository"] == "https://github.com/lcnetdev/marc2bibframe2"
    assert info["tag"].startswith("v")
    assert len(info["commit"]) == 40


def test_unreadable_marc_is_an_error():
    with pytest.raises(ValueError):
        marc_to_marcxml(b"this is not a MARC record")
