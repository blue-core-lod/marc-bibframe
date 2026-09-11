import http.client
import io
import pathlib
import urllib.error
import urllib.request

import lxml.etree as ET
import pymarc
import pytest
from rdflib import Graph

from marc_bibframe import (
    AuthorityLookupWarning,
    bibframe_marc,
    bibframe_to_marc,
    bibframe_to_marcxml,
    marcxml_to_rdfxml,
    upstream,
)

MARC = "{http://www.loc.gov/MARC21/slim}"
XSL = "{http://www.w3.org/1999/XSL/Transform}"

GENRE_FORM_URL = "https://id.loc.gov/authorities/genreForms/gf2014026339.marcxml.xml"


class FakeResponse:
    def __init__(self, data: bytes):
        self.data = data

    def read(self) -> bytes:
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        return False


class Service:
    """A stand-in for id.loc.gov, recording what was asked of it.

    Each outcome is either bytes to hand back or an exception to raise; the
    last one repeats once the rest are used up.
    """

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.asked: list[str] = []

    def install(self, monkeypatch):
        monkeypatch.setattr(urllib.request, "urlopen", self)
        return self

    def __call__(self, request, timeout=None):
        self.asked.append(request.full_url)
        outcome = self.outcomes[min(len(self.asked) - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


def http_error(code: int, retry_after=None) -> urllib.error.HTTPError:
    headers = http.client.HTTPMessage()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(GENRE_FORM_URL, code, "nope", headers, None)


def records(marcxml: bytes) -> list[ET._Element]:
    return ET.fromstring(marcxml).findall(f"{MARC}record")


def tags(marcxml: bytes) -> list[str | None]:
    return [
        field.get("tag") for field in ET.fromstring(marcxml).iter(f"{MARC}datafield")
    ]


def field(marcxml: bytes, tag: str) -> ET._Element:
    found = [
        f
        for f in ET.fromstring(marcxml).iter(f"{MARC}datafield")
        if f.get("tag") == tag
    ]
    assert len(found) == 1, f"expected one {tag}, found {len(found)}"
    return found[0]


def subfields(datafield: ET._Element) -> list[tuple[str | None, str | None]]:
    return [(s.get("code"), s.text) for s in datafield]


@pytest.fixture
def offline_kwargs():
    return {"authority_lookup": False, "generation_datestamp": "20260101000000.0"}


def test_returns_a_marcxml_collection(verne_bibframe, offline_kwargs):
    marcxml = bibframe_to_marcxml(verne_bibframe, **offline_kwargs)
    assert marcxml.startswith(b"<?xml version=")
    assert b'xmlns="http://www.loc.gov/MARC21/slim"' in marcxml
    assert len(records(marcxml)) == 1


def test_round_trip_from_marc(verne_marc, offline_kwargs):
    """MARC through BIBFRAME and back keeps the bibliographic core."""
    from marc_bibframe import marc_to_marcxml

    rdfxml = marcxml_to_rdfxml(marc_to_marcxml(verne_marc))
    marcxml = bibframe_to_marcxml(rdfxml, **offline_kwargs)

    assert ET.fromstring(marcxml).find(f"{MARC}record/{MARC}leader") is not None
    assert {"100", "245", "336", "337"} <= set(tags(marcxml))
    assert subfields(field(marcxml, "245"))[0] == (
        "a",
        "Twenty thousand leagues under the sea /",
    )


def test_record_id_lands_in_the_001(verne_bibframe, offline_kwargs):
    marcxml = bibframe_to_marcxml(
        verne_bibframe, record_id="99123456", **offline_kwargs
    )
    controlfields = {
        f.get("tag"): f.text for f in ET.fromstring(marcxml).iter(f"{MARC}controlfield")
    }
    assert controlfields["001"] == "99123456"


def test_record_id_comes_from_the_description_when_unset(
    verne_bibframe, offline_kwargs
):
    """pRecordId defaults to a sentinel meaning "use the record's own id"."""
    marcxml = bibframe_to_marcxml(verne_bibframe, **offline_kwargs)
    first = next(ET.fromstring(marcxml).iter(f"{MARC}controlfield"))
    assert first.get("tag") == "001"
    assert first.text not in (None, "", "default")


def test_datestamp_lands_in_the_005(verne_bibframe):
    marcxml = bibframe_to_marcxml(
        verne_bibframe, authority_lookup=False, generation_datestamp="20260101000000.0"
    )
    controlfields = {
        f.get("tag"): f.text for f in ET.fromstring(marcxml).iter(f"{MARC}controlfield")
    }
    assert controlfields["005"] == "20260101000000.0"


def test_offline_output_is_reproducible(verne_bibframe, offline_kwargs):
    assert bibframe_to_marcxml(verne_bibframe, **offline_kwargs) == bibframe_to_marcxml(
        verne_bibframe, **offline_kwargs
    )


def test_conversion_agency_and_source_reach_the_884(verne_bibframe, offline_kwargs):
    marcxml = bibframe_to_marcxml(
        verne_bibframe,
        source_record_id="ocn12345",
        conversion_agency="CSt",
        generation_uri="https://example.edu/convert",
        **offline_kwargs,
    )
    values = dict(subfields(field(marcxml, "884")))

    assert values["q"] == "CSt"
    assert values["k"] == "ocn12345"
    # the stylesheet treats the generation URI as a base and hangs the
    # bibframe2marc release off it
    generation_uri = values["u"] or ""
    assert generation_uri.startswith("https://example.edu/convert")
    assert upstream("bibframe2marc")["tag"] in generation_uri


# --- authority lookups -----------------------------------------------------


def test_lookup_completes_the_655(verne_bibframe, genre_form_authority, monkeypatch):
    """The regression test for the vendored patch.

    Without it the transform takes libxslt's crippled path: the genre form goes
    through an SRU gateway that libxml2 cannot even reach, and the 655 comes out
    with an empty tag. With it, the authority record is fetched straight over
    HTTPS and the field is whole.
    """
    service = Service(genre_form_authority).install(monkeypatch)

    marcxml = bibframe_to_marcxml(
        verne_bibframe, generation_datestamp="20260101000000.0"
    )

    assert service.asked == [GENRE_FORM_URL]
    assert subfields(field(marcxml, "655")) == [
        ("a", "Fiction"),
        ("2", "lcgft"),
        ("0", "http://id.loc.gov/authorities/genreForms/gf2014026339"),
    ]
    assert field(marcxml, "655").get("ind2") == "7"


def test_without_lookup_the_655_loses_its_tag(verne_bibframe, offline_kwargs):
    """Pin the degradation rather than pretend it is not there."""
    marcxml = bibframe_to_marcxml(verne_bibframe, **offline_kwargs)
    assert "655" not in tags(marcxml)
    assert "" in tags(marcxml)


def test_the_patched_parameter_reaches_the_generated_stylesheet():
    """Guards the patch: a misplaced namespace prefix would silently drop it."""
    directory = bibframe_marc.resource_dir("bf2marc")
    compiler = ET.XSLT(ET.parse(str(directory / "compile.xsl")))
    generated = compiler(bibframe_marc._rules_manifest(directory))
    params = {
        element.get("name")
        for element in generated.getroot()
        if element.tag == f"{XSL}param"
    }
    assert "pHttpsAvailable" in params


def test_lookups_are_cached_across_conversions(
    verne_bibframe, genre_form_authority, monkeypatch
):
    service = Service(genre_form_authority).install(monkeypatch)
    for _ in range(3):
        bibframe_to_marcxml(verne_bibframe, generation_datestamp="20260101000000.0")
    assert service.asked == [GENRE_FORM_URL]


def test_a_429_is_retried_after_the_requested_wait(
    verne_bibframe, genre_form_authority, monkeypatch
):
    service = Service(http_error(429, retry_after=7), genre_form_authority)
    service.install(monkeypatch)
    slept = []
    monkeypatch.setattr(bibframe_marc.time, "sleep", slept.append)

    marcxml = bibframe_to_marcxml(
        verne_bibframe, generation_datestamp="20260101000000.0"
    )

    assert len(service.asked) == 2
    assert slept == [7.0]
    assert subfields(field(marcxml, "655"))[0] == ("a", "Fiction")


def test_a_429_without_a_header_backs_off_exponentially(
    verne_bibframe, genre_form_authority, monkeypatch
):
    service = Service(http_error(429), http_error(429), genre_form_authority)
    service.install(monkeypatch)
    slept = []
    monkeypatch.setattr(bibframe_marc.time, "sleep", slept.append)

    bibframe_to_marcxml(verne_bibframe, generation_datestamp="20260101000000.0")

    assert slept == [1.0, 2.0]


def test_retry_after_is_capped(verne_bibframe, genre_form_authority, monkeypatch):
    service = Service(http_error(503, retry_after=99999), genre_form_authority)
    service.install(monkeypatch)
    slept = []
    monkeypatch.setattr(bibframe_marc.time, "sleep", slept.append)

    bibframe_to_marcxml(verne_bibframe, generation_datestamp="20260101000000.0")

    assert slept == [bibframe_marc._MAX_RETRY_WAIT]


def test_a_failed_lookup_warns_and_still_converts(verne_bibframe, monkeypatch):
    Service(http_error(404)).install(monkeypatch)

    with pytest.warns(AuthorityLookupWarning, match="1 authority lookup"):
        marcxml = bibframe_to_marcxml(
            verne_bibframe, generation_datestamp="20260101000000.0"
        )

    assert len(records(marcxml)) == 1
    assert "655" not in tags(marcxml)


def test_a_failed_lookup_is_not_retried_forever(verne_bibframe, monkeypatch):
    """A 404 is final: no retries, and remembered for the rest of the process."""
    service = Service(http_error(404)).install(monkeypatch)

    with pytest.warns(AuthorityLookupWarning):
        bibframe_to_marcxml(verne_bibframe, generation_datestamp="20260101000000.0")
    with pytest.warns(AuthorityLookupWarning):
        bibframe_to_marcxml(verne_bibframe, generation_datestamp="20260101000000.0")

    assert len(service.asked) == 1


def test_request_delay_waits_between_requests_but_not_on_cache_hits(
    verne_bibframe, genre_form_authority, monkeypatch
):
    bibframe_marc._transform.cache_clear()
    Service(genre_form_authority).install(monkeypatch)
    slept = []
    monkeypatch.setattr(bibframe_marc.time, "sleep", slept.append)

    # the first request of the process has nothing to wait behind
    bibframe_to_marcxml(
        verne_bibframe, request_delay=0.25, generation_datestamp="20260101000000.0"
    )
    assert slept == []

    # and the second conversion is answered from the cache
    bibframe_to_marcxml(
        verne_bibframe, request_delay=0.25, generation_datestamp="20260101000000.0"
    )
    assert slept == []

    bibframe_marc.clear_authority_cache()
    bibframe_to_marcxml(
        verne_bibframe, request_delay=0.25, generation_datestamp="20260101000000.0"
    )
    assert slept == [0.25]


def test_no_lookup_means_no_requests(verne_bibframe, offline_kwargs):
    """The autouse offline fixture makes any request an error, so this is the test."""
    assert bibframe_to_marcxml(verne_bibframe, **offline_kwargs)


def test_user_agent_identifies_the_project(
    verne_bibframe, genre_form_authority, monkeypatch
):
    seen = []

    def urlopen(request, timeout=None):
        seen.append(request.get_header("User-agent"))
        return FakeResponse(genre_form_authority)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    bibframe_to_marcxml(verne_bibframe, generation_datestamp="20260101000000.0")

    assert seen and seen[0].startswith("marc-bibframe/")
    assert "github.com/blue-core-lod/marc-bibframe" in seen[0]


# --- input shape -----------------------------------------------------------


def test_several_descriptions_become_several_records(
    two_record_bibframe, offline_kwargs
):
    assert len(ET.fromstring(two_record_bibframe)) == 4  # two Works, two Instances

    marcxml = bibframe_to_marcxml(two_record_bibframe, **offline_kwargs)
    assert len(records(marcxml)) == 2


def test_record_id_is_refused_for_several_descriptions(
    two_record_bibframe, offline_kwargs
):
    with pytest.raises(ValueError, match="cannot apply to 2 descriptions"):
        bibframe_to_marcxml(two_record_bibframe, record_id="1", **offline_kwargs)


# --- input formats ---------------------------------------------------------


@pytest.fixture
def verne_graph(verne_bibframe) -> Graph:
    graph = Graph()
    graph.parse(data=verne_bibframe, format="xml")
    return graph


@pytest.mark.parametrize(
    ("name", "serialization"),
    [
        ("turtle", "turtle"),
        ("ttl", "turtle"),
        ("ntriples", "nt"),
        ("nt", "nt"),
        ("json-ld", "json-ld"),
        ("jsonld", "json-ld"),
        ("xml", "xml"),
    ],
)
def test_every_format_converts_the_same_as_striped_rdfxml(
    name, serialization, verne_bibframe, verne_graph, offline_kwargs
):
    """The striper has to be faithful, not merely acceptable.

    Whichever way the graph arrives, it has to reach the stylesheet in a shape
    that yields the very same MARC as marc2bibframe2's own RDF/XML does.
    """
    striped = bibframe_to_marcxml(verne_bibframe, record_id="1", **offline_kwargs)
    restriped = bibframe_to_marcxml(
        verne_graph.serialize(format=serialization),
        format=name,
        record_id="1",
        **offline_kwargs,
    )
    assert restriped == striped


@pytest.mark.parametrize("serialization", ["turtle", "nt", "json-ld", "xml"])
def test_the_format_is_guessed_when_unset(
    serialization, verne_bibframe, verne_graph, offline_kwargs
):
    striped = bibframe_to_marcxml(verne_bibframe, record_id="1", **offline_kwargs)
    guessed = bibframe_to_marcxml(
        verne_graph.serialize(format=serialization), record_id="1", **offline_kwargs
    )
    assert guessed == striped


def test_a_graph_can_be_handed_over_directly(
    verne_bibframe, verne_graph, offline_kwargs
):
    assert bibframe_to_marcxml(
        verne_graph, record_id="1", **offline_kwargs
    ) == bibframe_to_marcxml(verne_bibframe, record_id="1", **offline_kwargs)


def test_unstriped_rdfxml_is_restriped_rather_than_refused(
    verne_bibframe, verne_graph, offline_kwargs
):
    """rdflib does not nest the graph the way the stylesheet demands."""
    unstriped = verne_graph.serialize(format="xml", encoding="utf-8")
    assert b"<bf:Instance" not in unstriped.split(b"<bf:Work")[0][:200]

    assert bibframe_to_marcxml(
        unstriped, record_id="1", **offline_kwargs
    ) == bibframe_to_marcxml(verne_bibframe, record_id="1", **offline_kwargs)


def test_format_rdfxml_insists_on_striped_input(verne_graph, offline_kwargs):
    """Asking for rdfxml explicitly means the cheap path, or an error."""
    with pytest.raises(ValueError, match="not striped"):
        bibframe_to_marcxml(
            verne_graph.serialize(format="xml", encoding="utf-8"),
            format="rdfxml",
            **offline_kwargs,
        )


def test_an_unknown_format_is_refused(verne_bibframe, offline_kwargs):
    with pytest.raises(ValueError, match="unknown format 'n3'"):
        bibframe_to_marcxml(verne_bibframe, format="n3", **offline_kwargs)


def test_unparsable_input_says_so(offline_kwargs):
    with pytest.raises(ValueError, match="could not read the input as turtle"):
        bibframe_to_marcxml("this is not turtle at all {[", **offline_kwargs)


def test_a_graph_with_no_instance_says_so(offline_kwargs):
    graph = Graph()
    graph.parse(
        data="<http://example.edu/w> a <http://id.loc.gov/ontologies/bibframe/Work> .",
        format="turtle",
    )
    with pytest.raises(ValueError, match="no bf:Instance in the graph"):
        bibframe_to_marcxml(graph, **offline_kwargs)


def test_several_instances_in_a_graph_become_several_records(
    two_record_bibframe, offline_kwargs
):
    graph = Graph()
    graph.parse(data=two_record_bibframe, format="xml")
    marcxml = bibframe_to_marcxml(graph.serialize(format="turtle"), **offline_kwargs)
    assert len(records(marcxml)) == 2


# LC's own test descriptions, each of which caught a way the striper can be
# unfaithful. See tests/fixtures/descriptions/README.md.
DESCRIPTIONS = pathlib.Path(__file__).parent / "fixtures" / "descriptions"


@pytest.mark.parametrize(
    ("description", "tag", "detail"),
    [
        # An rdf:parseType="Collection" holding a madsrdf:elementList. Rebuilt
        # as an rdf:first/rdf:rest chain the rules cannot read it, and the
        # heading loses its $a.
        ("111.xml", "111", ("a", "Codex Book Fair and Symposium.")),
        # A node typed both bf:Hub and bf:Arrangement. Named after the specific
        # class instead of the general one, the 240 rule never fires.
        ("240.xml", "240", ("a", "Sonata for kazoo. arr.")),
        # An xsd:duration of PT00H31M00S, which rdflib rewrites to PT31M as it
        # parses unless told not to -- and the 306 with it.
        ("306-02.xml", "306", ("a", "003100")),
    ],
)
def test_striping_keeps_what_the_rules_read(description, tag, detail, offline_kwargs):
    source = (DESCRIPTIONS / description).read_bytes()

    direct = bibframe_to_marcxml(source, format="rdfxml", **offline_kwargs)
    restriped = bibframe_to_marcxml(source, format="xml", **offline_kwargs)

    assert detail in subfields(field(direct, tag)), "the fixture itself is wrong"
    assert subfields(field(restriped, tag)) == subfields(field(direct, tag))


def test_striping_matches_splitting_for_several_records(
    two_record_bibframe, offline_kwargs
):
    graph = Graph()
    graph.parse(data=two_record_bibframe, format="xml")
    assert bibframe_to_marcxml(
        graph.serialize(format="turtle"), **offline_kwargs
    ) == bibframe_to_marcxml(two_record_bibframe, **offline_kwargs)


def test_accepts_str_and_bytes(verne_bibframe, offline_kwargs):
    """lxml refuses a str carrying an encoding declaration, so we encode first."""
    assert verne_bibframe.startswith(b"<?xml")
    assert bibframe_to_marcxml(
        verne_bibframe.decode(), **offline_kwargs
    ) == bibframe_to_marcxml(verne_bibframe, **offline_kwargs)


# --- binary MARC -----------------------------------------------------------


def test_bibframe_to_marc_is_readable_by_pymarc(verne_bibframe, offline_kwargs):
    marc = bibframe_to_marc(verne_bibframe, record_id="99123456", **offline_kwargs)
    parsed = list(pymarc.MARCReader(io.BytesIO(marc)))

    assert len(parsed) == 1
    assert parsed[0] is not None
    assert parsed[0]["001"].data == "99123456"
    assert parsed[0].title == "Twenty thousand leagues under the sea /"


def test_bibframe_to_marc_handles_several_records(two_record_bibframe, offline_kwargs):
    marc = bibframe_to_marc(two_record_bibframe, **offline_kwargs)
    assert len(list(pymarc.MARCReader(io.BytesIO(marc)))) == 2


# --- vendoring -------------------------------------------------------------


def test_upstream_reports_both_stylesheets():
    assert upstream()["repository"].endswith("marc2bibframe2")
    assert upstream("bibframe2marc")["repository"].endswith("bibframe2marc")
    assert upstream("bibframe2marc")["tag"].startswith("v")


def test_upstream_rejects_an_unknown_stylesheet():
    with pytest.raises(ValueError, match="unknown stylesheet"):
        upstream("marc2marc")


@pytest.mark.live
def test_live_authority_lookup(verne_bibframe):
    """The real thing, against id.loc.gov. Deselected by default."""
    marcxml = bibframe_to_marcxml(
        verne_bibframe, generation_datestamp="20260101000000.0"
    )
    assert subfields(field(marcxml, "655"))[0] == ("a", "Fiction")
