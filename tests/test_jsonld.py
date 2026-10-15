"""The bibframe-json shape on the way out, and reading it back on the way in.

marc-bibframe writes JSON-LD as the bounded description that bibframe-json
defines rather than as rdflib's flat array of expanded nodes. The claim that it
is that shape is worth nothing unless it holds, so these tests check the output
against the schema bibframe-json ships rather than against a stored fixture --
the schema is the authority, and a fixture would drift the moment the context
did.
"""

import json

import bibframe_json
import pytest

from marc_bibframe import (
    bibframe_to_marcxml,
    marc_to_jsonld,
    marcxml_to_jsonld,
    marcxml_to_rdfxml,
)

#: Pinned so two conversions of the same record are comparable at all; the
#: transform otherwise stamps the current time into the work's admin metadata.
STAMP = "2026-09-01T00:00:00"


@pytest.fixture
def offline_kwargs():
    """The reverse direction with no lookups and a pinned datestamp.

    So that it is reproducible and touches no network -- the same bag
    test_bibframe_marc.py uses.
    """
    return {"authority_lookup": False, "generation_datestamp": "20260101000000.0"}


def document(marcxml, **kwargs):
    return json.loads(marcxml_to_jsonld(marcxml, generation_datestamp=STAMP, **kwargs))


def test_a_single_record_is_the_instance_itself(verne_marcxml):
    """The document is the Instance, not an array or a @graph around one."""
    instance = document(verne_marcxml)

    assert instance["@context"] == bibframe_json.CONTEXT_URL
    assert "@graph" not in instance
    assert instance["@id"] == "http://example.org/99123456#Instance"
    assert instance["@type"] == ["Instance"]


def test_the_work_is_embedded_where_instance_of_reaches_it(verne_marcxml):
    """A bounded description needs no second fetch: the Work is right there."""
    instance = document(verne_marcxml)
    work = instance["instanceOf"][0]

    assert isinstance(work, dict)  # embedded, not the bare URI a linked one holds
    assert work["@id"] == "http://example.org/99123456#Work"
    assert "Work" in work["@type"]


def test_every_property_is_an_array(verne_marcxml):
    """So a reader can loop without checking whether this one is a single value.

    Keyword properties are the exception: @id, @value, @language and @context
    hold one thing by definition, and @type is one datatype IRI on a value
    object but a list of classes on a node.
    """
    keywords = {
        "@context",
        "@id",
        "@value",
        "@language",
        "@direction",
        "@index",
        "@type",
    }

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key not in keywords:
                    assert isinstance(value, list), f"{key} is not an array"
                walk(value)

    walk(document(verne_marcxml))


def test_blank_nodes_carry_no_identifier(verne_marcxml):
    """A `_:b0` addresses nothing outside the document it appears in."""
    assert b'"_:' not in marcxml_to_jsonld(verne_marcxml, generation_datestamp=STAMP)


def test_the_bounded_description_validates(verne_marcxml):
    """Against the schema bibframe-json ships, which is the real assertion.

    Ontology warnings are left out: they are about the vocabulary disagreeing
    with itself, which is not this package's to fix.
    """
    findings = bibframe_json.validate(
        document(verne_marcxml), ontology=False, kind=bibframe_json.BOUNDED
    )
    assert findings == []


def test_several_records_become_a_graph_of_instances(two_record_marcxml):
    """A collection has no single Instance to root on, so it is a @graph."""
    doc = document(two_record_marcxml)

    assert set(doc) == {"@context", "@graph"}
    instances = doc["@graph"]
    ids = [node["@id"] for node in instances]

    assert ids == sorted(ids)  # Instance order, so nothing depends on parsing
    assert [node["@type"] for node in instances] == [["Instance"], ["Instance"]]


def test_every_instance_in_a_graph_is_a_bounded_description(two_record_marcxml):
    for instance in document(two_record_marcxml)["@graph"]:
        # A @graph member is the same document with the context lifted to the
        # top, which is where the schema requires it.
        findings = bibframe_json.validate(
            {"@context": bibframe_json.CONTEXT_URL, **instance},
            ontology=False,
            kind=bibframe_json.BOUNDED,
        )
        assert findings == [], instance["@id"]


def test_non_latin_text_is_not_escaped(verne_marcxml):
    """BIBFRAME is full of it, and escaping it makes a readable format unreadable."""
    marcxml = verne_marcxml.replace(
        "Twenty thousand leagues under the sea", "Двадцать тысяч лье под водой"
    )
    text = marcxml_to_jsonld(marcxml, generation_datestamp=STAMP).decode("utf-8")

    assert "Двадцать тысяч лье под водой" in text
    assert "\\u" not in text


def test_marc_to_jsonld_reads_binary_marc(verne_marc, verne_marcxml):
    """marc_to_jsonld is marc_to_marcxml piped into the transform.

    Compared by identifier rather than byte for byte: the two routes build
    separate graphs, and rdflib labels blank nodes afresh each parse.
    """
    from_binary = json.loads(marc_to_jsonld(verne_marc, generation_datestamp=STAMP))
    from_xml = document(verne_marcxml)

    assert from_binary["@id"] == from_xml["@id"]
    assert from_binary["@context"] == from_xml["@context"]


def test_it_reads_back_to_the_same_marc(verne_marcxml, offline_kwargs):
    """The round trip, offline: the shape is not lossy for the MARC it came from."""
    from_jsonld = bibframe_to_marcxml(
        marcxml_to_jsonld(verne_marcxml, generation_datestamp=STAMP),
        record_id="1",
        **offline_kwargs,
    )
    from_rdfxml = bibframe_to_marcxml(
        marcxml_to_rdfxml(verne_marcxml, generation_datestamp=STAMP),
        format="rdfxml",
        record_id="1",
        **offline_kwargs,
    )
    assert from_jsonld == from_rdfxml


def test_a_graph_with_no_instance_is_refused():
    """There is nothing to root a bounded description on."""
    from rdflib import Graph

    from marc_bibframe._jsonld import bounded_document

    with pytest.raises(ValueError, match="no bf:Instance"):
        bounded_document(Graph())
