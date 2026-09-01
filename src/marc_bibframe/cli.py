"""Command line interface: MARC in, BIBFRAME out."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from marc_bibframe import (
    DEFAULT_BASE_URI,
    marc_to_marcxml,
    marcxml_to_graph,
    marcxml_to_rdfxml,
    upstream,
)

# rdflib's name for each, except rdfxml, which we serve from the transform
# directly rather than round-tripping it through a parse.
FORMATS = {
    "turtle": "turtle",
    "ttl": "turtle",
    "json-ld": "json-ld",
    "jsonld": "json-ld",
    "ntriples": "nt",
    "nt": "nt",
    "xml": "xml",
    "rdfxml": None,
}


def looks_like_marcxml(data: bytes) -> bool:
    return data.lstrip().lstrip(b"\xef\xbb\xbf").startswith(b"<")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="marc-bibframe",
        description="Convert MARC records to BIBFRAME RDF.",
        epilog="Binary MARC21 and MARCXML are both accepted; the format is "
        "detected from the content. With no INPUT, reads standard input.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="MARC file to convert, or - for standard input (the default)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="write to this file instead of standard output",
    )
    parser.add_argument(
        "-f",
        "--format",
        default="turtle",
        choices=sorted(FORMATS),
        help="output serialization (default: turtle). rdfxml is the "
        "stylesheet's own output, passed through unparsed",
    )
    parser.add_argument(
        "-b",
        "--baseuri",
        default=DEFAULT_BASE_URI,
        metavar="URI",
        help="base for the URIs the transform mints, which are NOT authority "
        f"URIs -- see the README (default: {DEFAULT_BASE_URI})",
    )
    parser.add_argument(
        "--idfield",
        metavar="FIELD",
        help="MARC field holding the record id, 001 by default. Suffix a "
        "subfield code to use one, e.g. 035a",
    )
    parser.add_argument(
        "--idsource",
        metavar="URI",
        help="URI identifying the source of the record id, e.g. "
        "http://id.loc.gov/vocabulary/organizations/dlc",
    )
    parser.add_argument(
        "--local-fields",
        action="store_true",
        default=None,
        help="convert fields the Library of Congress defines locally, e.g. 859",
    )
    parser.add_argument(
        "--no-bcp47-inference",
        dest="bcp47_inference",
        action="store_false",
        default=None,
        help="keep the script subtag in BCP-47 codes even when the language implies it",
    )
    parser.add_argument(
        "--datestamp",
        metavar="TIMESTAMP",
        help="override the timestamp in the work's admin metadata. With "
        "-f rdfxml this makes output byte-for-byte reproducible; other "
        "formats still vary, as rdflib renames blank nodes on each run",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"marc-bibframe, marc2bibframe2 {upstream()['tag']}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.input == "-":
        data = sys.stdin.buffer.read()
    else:
        path = Path(args.input)
        if not path.exists():
            sys.exit(f"marc-bibframe: {path}: no such file")
        data = path.read_bytes()

    if not data.strip():
        sys.exit("marc-bibframe: no input")

    marcxml = data if looks_like_marcxml(data) else marc_to_marcxml(data)

    params = {
        "baseuri": args.baseuri,
        "idfield": args.idfield,
        "idsource": args.idsource,
        "localfields": args.local_fields,
        "bcp47_inference": args.bcp47_inference,
        "generation_datestamp": args.datestamp,
    }

    rdflib_format = FORMATS[args.format]
    if rdflib_format is None:
        out = marcxml_to_rdfxml(marcxml, **params)
    else:
        out = marcxml_to_graph(marcxml, **params).serialize(
            format=rdflib_format, encoding="utf-8"
        )

    if args.output:
        Path(args.output).write_bytes(out)
    else:
        sys.stdout.buffer.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
