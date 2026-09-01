import pytest

from marc_bibframe.cli import looks_like_marcxml, main

from .conftest import FIXTURES

VERNE_MRC = str(FIXTURES / "verne.mrc")
VERNE_XML = str(FIXTURES / "verne.xml")


def run(capsys, *argv):
    assert main(list(argv)) == 0
    return capsys.readouterr().out


def test_converts_binary_marc(capsys):
    assert "Verne, Jules, 1828-1905" in run(capsys, VERNE_MRC)


def test_converts_marcxml(capsys):
    assert "Verne, Jules, 1828-1905" in run(capsys, VERNE_XML)


def test_input_format_is_detected_not_declared(capsys):
    """The same record as binary MARC and as MARCXML converts identically."""
    from_marc = sorted(run(capsys, VERNE_MRC, "-f", "rdfxml").splitlines())
    from_marcxml = sorted(run(capsys, VERNE_XML, "-f", "rdfxml").splitlines())
    assert from_marc == from_marcxml


def test_reads_stdin_by_default(capsys, monkeypatch):
    class Stdin:
        buffer = open(VERNE_MRC, "rb")  # noqa: SIM115

    monkeypatch.setattr("sys.stdin", Stdin)
    assert "Verne, Jules, 1828-1905" in run(capsys)


@pytest.mark.parametrize(
    ("fmt", "marker"),
    [
        ("turtle", "@prefix bf:"),
        ("ttl", "@prefix bf:"),
        ("nt", "<http://example.org/99123456#Work>"),
        ("ntriples", "<http://example.org/99123456#Work>"),
        ("json-ld", '"@id"'),
        ("xml", "<rdf:RDF"),
        ("rdfxml", "<rdf:RDF"),
    ],
)
def test_output_formats(capsys, fmt, marker):
    assert marker in run(capsys, VERNE_XML, "-f", fmt)


def test_rdfxml_is_the_stylesheet_output_not_a_reserialization(capsys):
    """rdfxml skips rdflib entirely, so it keeps the transform's own shape."""
    passthrough = run(capsys, VERNE_XML, "-f", "rdfxml")
    reserialized = run(capsys, VERNE_XML, "-f", "xml")
    assert "<bf:Work" in passthrough
    assert passthrough != reserialized


def test_baseuri(capsys):
    assert "https://example.edu/c/99123456#Work" in run(
        capsys, VERNE_XML, "-b", "https://example.edu/c/", "-f", "nt"
    )


def test_writes_to_a_file(tmp_path, capsys):
    out = tmp_path / "verne.ttl"
    assert main([VERNE_XML, "-o", str(out)]) == 0
    assert capsys.readouterr().out == ""
    assert "Verne, Jules, 1828-1905" in out.read_text()


def test_datestamp_makes_runs_identical(capsys):
    """Only for rdfxml: rdflib re-mints blank node labels on every serialization."""
    args = (VERNE_XML, "--datestamp", "2026-09-01T00:00:00", "-f", "rdfxml")
    assert run(capsys, *args) == run(capsys, *args)
    assert "2026-09-01T00:00:00" in run(capsys, *args)


def test_missing_file_is_an_error():
    with pytest.raises(SystemExit) as excinfo:
        main(["/does/not/exist.mrc"])
    assert "no such file" in str(excinfo.value)


def test_empty_input_is_an_error(tmp_path):
    empty = tmp_path / "empty.mrc"
    empty.write_bytes(b"")
    with pytest.raises(SystemExit) as excinfo:
        main([str(empty)])
    assert "no input" in str(excinfo.value)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"<collection>", True),
        (b"  \n<record>", True),
        (b"\xef\xbb\xbf<record>", True),
        (b'<?xml version="1.0"?><record>', True),
        (b"00714cam a2200205 a 4500", False),
    ],
)
def test_looks_like_marcxml(data, expected):
    assert looks_like_marcxml(data) is expected
