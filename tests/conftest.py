import re
import urllib.request
from pathlib import Path

import pytest

from marc_bibframe import clear_authority_cache, marcxml_to_rdfxml

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def verne_marcxml() -> str:
    return (FIXTURES / "verne.xml").read_text()


@pytest.fixture
def verne_marc() -> bytes:
    return (FIXTURES / "verne.mrc").read_bytes()


@pytest.fixture
def russian_marcxml() -> str:
    return (FIXTURES / "russian-no-script.xml").read_text()


@pytest.fixture
def series_marcxml() -> str:
    return (FIXTURES / "series-490.xml").read_text()


@pytest.fixture
def verne_bibframe() -> bytes:
    """Verne converted to BIBFRAME RDF/XML, with the datestamp pinned."""
    return (FIXTURES / "verne-bibframe.xml").read_bytes()


@pytest.fixture
def two_record_bibframe(verne_marcxml) -> bytes:
    """Two BIBFRAME descriptions in one RDF/XML document.

    marc2bibframe2 emits a Work and an Instance for every record it is given,
    so anything converted from a multi-record file has to be taken apart again
    on the way back.
    """
    match = re.search(r"<record.*?</record>", verne_marcxml, re.DOTALL)
    assert match is not None
    record = match.group(0)
    collection = (
        '<collection xmlns="http://www.loc.gov/MARC21/slim">'
        + record
        + record.replace("99123456", "99654321")
        + "</collection>"
    )
    return marcxml_to_rdfxml(collection)


@pytest.fixture
def genre_form_authority() -> bytes:
    """id.loc.gov's MARCXML for the lcgft term the verne record cites."""
    return (FIXTURES / "authorities" / "gf2014026339.marcxml.xml").read_bytes()


@pytest.fixture(autouse=True)
def offline(request, monkeypatch):
    """Fail loudly rather than slowly if a test reaches the network.

    Authority lookups are on by default, so a test that neither stubs nor
    disables them would otherwise quietly talk to id.loc.gov. Tests that mean
    to reach the network say so with the ``network`` or ``live`` marker.
    """
    clear_authority_cache()
    if {"network", "live"} & set(request.keywords):
        return

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "this test reached the network; stub urlopen or pass authority_lookup=False"
        )

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
