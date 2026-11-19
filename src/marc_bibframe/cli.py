"""Command line interface: MARC in, BIBFRAME out."""

from __future__ import annotations

import argparse

from marc_bibframe import (
    DEFAULT_BASE_URI,
    marc_to_marcxml,
    marcxml_to_graph,
    marcxml_to_jsonld,
    marcxml_to_rdfxml,
    upstream,
)
from marc_bibframe._cli import read_input, write_output
from marc_bibframe._jsonld import dumps, expanded

#: rdflib's name for each output, except where the output does not come from
#: rdflib at all. json-ld is a bibframe-json bounded document and rdfxml is
#: served from the transform directly rather than round-tripped through a
#: parse; json-ld-expanded is the flat array of expanded nodes, kept for anyone
#: who wants the RDF dump rather than the readable shape, and written by pyld
#: because rdflib's loses blank nodes before rdflib 8 (rdflib PR 3679), which
#: is not released yet.
FORMATS = {
    "turtle": "turtle",
    "ttl": "turtle",
    "json-ld": "bibframe-json",
    "jsonld": "bibframe-json",
    "json-ld-expanded": "json-ld-expanded",
    "ntriples": "nt",
    "nt": "nt",
    "xml": "xml",
    "rdfxml": "rdfxml",
}

#: The values in :data:`FORMATS` that are not rdflib format strings.
BIBFRAME_JSON = "bibframe-json"
EXPANDED_JSON = "json-ld-expanded"
RDFXML = "rdfxml"


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
        help="output serialization (default: turtle). json-ld is the "
        "bibframe-json shape, one Instance per record and the Work embedded; "
        "json-ld-expanded is the flat array of expanded nodes; rdfxml is the "
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
        "--blank-nodes",
        action="store_true",
        help="describe the resources MARC does not identify (the work and "
        "instance, hubs, items, headings without a $0) as blank nodes rather "
        "than by minted URIs. Only with -f nt, -f xml or -f json-ld-expanded, "
        "and not with --baseuri",
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

    data = read_input(args.input, "marc-bibframe")
    marcxml = data if looks_like_marcxml(data) else marc_to_marcxml(data)

    params = {
        "baseuri": args.baseuri,
        "idfield": args.idfield,
        "idsource": args.idsource,
        "localfields": args.local_fields,
        "bcp47_inference": args.bcp47_inference,
        "generation_datestamp": args.datestamp,
    }

    target = FORMATS[args.format]
    blank = args.blank_nodes
    if target == RDFXML:
        if blank:
            raise SystemExit(
                "marc-bibframe: --blank-nodes needs a format rdflib writes, not rdfxml"
            )
        out = marcxml_to_rdfxml(marcxml, **params)
    elif blank and target == "turtle":
        # rdflib's Turtle writer can write a list cell twice in these graphs
        # (https://github.com/RDFLib/rdflib/issues/3736), and turtle is the
        # default, so say which formats do work. When rdflib fixes it,
        # test_rdflib_turtle_writes_a_list_cell_once starts failing.
        raise SystemExit(
            "marc-bibframe: --blank-nodes cannot be written as turtle, which "
            "rdflib garbles for lists of blank nodes; use -f nt, -f xml or "
            "-f json-ld-expanded"
        )
    else:
        try:
            if target == BIBFRAME_JSON:
                out = marcxml_to_jsonld(marcxml, blank_nodes=blank, **params)
            elif target == EXPANDED_JSON:
                out = dumps(
                    expanded(marcxml_to_graph(marcxml, blank_nodes=blank, **params))
                )
            else:
                out = marcxml_to_graph(marcxml, blank_nodes=blank, **params).serialize(
                    format=target, encoding="utf-8"
                )
        except ValueError as error:
            raise SystemExit(f"marc-bibframe: {error}") from error

    write_output(out, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
