import io
import urllib.request

import pymarc
import pytest

from marc_bibframe.bf2marc_cli import main

from .conftest import FIXTURES

VERNE_BF = str(FIXTURES / "verne-bibframe.xml")
VERNE_XML = str(FIXTURES / "verne.xml")

OFFLINE = ("--no-authority-lookup", "--datestamp", "20260101000000.0")


def run(capsys, *argv):
    assert main(list(argv)) == 0
    return capsys.readouterr().out


def test_converts_to_marcxml(capsys):
    out = run(capsys, VERNE_BF, *OFFLINE)
    assert '<collection xmlns="http://www.loc.gov/MARC21/slim">' in out
    assert "Twenty thousand leagues under the sea /" in out


def test_record_id(capsys):
    out = run(capsys, VERNE_BF, "--record-id", "99123456", *OFFLINE)
    assert '<controlfield xml:space="preserve" tag="001">99123456</controlfield>' in out


def test_binary_marc_output(tmp_path):
    out = tmp_path / "verne.mrc"
    assert main([VERNE_BF, "-f", "marc", "-o", str(out), *OFFLINE]) == 0
    parsed = list(pymarc.MARCReader(io.BytesIO(out.read_bytes())))
    assert len(parsed) == 1
    assert parsed[0].title == "Twenty thousand leagues under the sea /"


def test_reads_stdin_by_default(capsys, monkeypatch):
    class Stdin:
        buffer = io.BytesIO(FIXTURES.joinpath("verne-bibframe.xml").read_bytes())

    monkeypatch.setattr("sys.stdin", Stdin)
    assert "Twenty thousand leagues under the sea /" in run(capsys, *OFFLINE)


def test_writes_to_a_file(tmp_path, capsys):
    out = tmp_path / "verne.xml"
    assert main([VERNE_BF, "-o", str(out), *OFFLINE]) == 0
    assert capsys.readouterr().out == ""
    assert "Twenty thousand leagues under the sea /" in out.read_text()


def test_datestamp_makes_runs_identical(capsys):
    assert run(capsys, VERNE_BF, *OFFLINE) == run(capsys, VERNE_BF, *OFFLINE)
    assert "20260101000000.0" in run(capsys, VERNE_BF, *OFFLINE)


def test_no_authority_lookup_touches_no_network(capsys):
    """The autouse offline fixture turns any request into an error."""
    assert run(capsys, VERNE_BF, *OFFLINE)


def test_lookups_are_on_without_the_flag(capsys, genre_form_authority, monkeypatch):
    asked = []

    class Response:
        def read(self):
            return genre_form_authority

        def __enter__(self):
            return self

        def __exit__(self, *exception):
            return False

    def urlopen(request, timeout=None):
        asked.append(request.full_url)
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    out = run(capsys, VERNE_BF, "--datestamp", "20260101000000.0")

    assert asked == [
        "https://id.loc.gov/authorities/genreForms/gf2014026339.marcxml.xml"
    ]
    assert '<datafield tag="655"' in out


def test_reads_every_format_marc_bibframe_writes(capsys, tmp_path):
    """The two command lines have to meet in the middle, whichever hop you pick."""
    from marc_bibframe.cli import main as forward

    for serialization in ["turtle", "json-ld", "ntriples", "xml", "rdfxml"]:
        rdf = tmp_path / f"verne.{serialization}"
        assert forward([VERNE_XML, "-f", serialization, "-o", str(rdf)]) == 0
        out = run(capsys, str(rdf), *OFFLINE)
        assert "Twenty thousand leagues under the sea /" in out, serialization


def test_input_format_can_be_named(capsys, tmp_path):
    from marc_bibframe.cli import main as forward

    rdf = tmp_path / "verne.ttl"
    assert forward([VERNE_XML, "-f", "turtle", "-o", str(rdf)]) == 0
    assert run(capsys, str(rdf), "-i", "turtle", *OFFLINE) == run(
        capsys, str(rdf), *OFFLINE
    )


def test_naming_rdfxml_for_unstriped_input_is_reported(tmp_path):
    from marc_bibframe.cli import main as forward

    rdf = tmp_path / "verne.xml"
    assert forward([VERNE_XML, "-f", "xml", "-o", str(rdf)]) == 0

    with pytest.raises(SystemExit) as exit:
        main([str(rdf), "-i", "rdfxml", *OFFLINE])
    assert "not striped" in str(exit.value)


def test_missing_file_is_an_error():
    with pytest.raises(SystemExit) as exit:
        main(["nope.xml"])
    assert "no such file" in str(exit.value)


def test_empty_input_is_an_error(tmp_path):
    empty = tmp_path / "empty.xml"
    empty.write_text("")
    with pytest.raises(SystemExit) as exit:
        main([str(empty)])
    assert "no input" in str(exit.value)


def test_binary_marc_input_points_at_the_other_command():
    with pytest.raises(SystemExit) as exit:
        main([str(FIXTURES / "verne.mrc"), *OFFLINE])
    assert "this is binary MARC21, not BIBFRAME" in str(exit.value)


def test_marcxml_input_points_at_the_other_command():
    """The likeliest mistake, with two sibling commands about."""
    with pytest.raises(SystemExit) as exit:
        main([VERNE_XML, *OFFLINE])
    assert "bibframe-marc:" in str(exit.value)
    assert "this is MARCXML, not BIBFRAME" in str(exit.value)


def test_record_id_with_several_descriptions_is_reported(tmp_path, two_record_bibframe):
    path = tmp_path / "two.xml"
    path.write_bytes(two_record_bibframe)

    with pytest.raises(SystemExit) as exit:
        main([str(path), "--record-id", "1", *OFFLINE])
    assert "cannot apply to 2 descriptions" in str(exit.value)


def test_version_reports_the_vendored_stylesheet(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "bibframe2marc v" in capsys.readouterr().out
