"""Command line interface: BIBFRAME in, MARC out."""

from __future__ import annotations

import argparse

from marc_bibframe import FORMATS, bibframe_to_marc, bibframe_to_marcxml, upstream
from marc_bibframe._cli import read_input, write_output

#: "auto" is the default: sniff the serialization from the input itself.
INPUT_FORMATS = ["auto", *sorted(FORMATS)]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bibframe-marc",
        description="Convert BIBFRAME RDF to MARC.",
        epilog="One MARC record comes out per bf:Instance in the input, so a "
        "graph describing several becomes a collection of several. With no "
        "INPUT, reads standard input.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="BIBFRAME RDF to convert, or - for standard input (the default)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="write to this file instead of standard output",
    )
    parser.add_argument(
        "-f",
        "--format",
        default="marcxml",
        choices=["marcxml", "marc"],
        help="output format (default: marcxml). marc is binary MARC21",
    )
    parser.add_argument(
        "-i",
        "--input-format",
        default="auto",
        choices=INPUT_FORMATS,
        help="input serialization, named as marc-bibframe names its output "
        "ones (default: auto, which sniffs it from the content). rdfxml goes "
        "straight to the stylesheet and must already be striped, as it is "
        "coming out of marc-bibframe; the rest are parsed into a graph and "
        "restriped",
    )
    parser.add_argument(
        "--record-id",
        metavar="ID",
        help="value for the 001. Left unset, each record's id comes from its "
        "own bf:Local identifier, or is generated. Cannot be used with input "
        "holding more than one description",
    )
    parser.add_argument(
        "--cat-script",
        metavar="SCRIPT",
        help="default cataloguing script for xml:lang attributes (default: Latn)",
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
        help="override the conversion timestamp, which lands in the 005 and "
        "the 884. With --no-authority-lookup this makes output byte-for-byte "
        "reproducible",
    )
    parser.add_argument(
        "--source-record-id",
        metavar="ID",
        help="source record id, recorded in the 884",
    )
    parser.add_argument(
        "--conversion-agency",
        metavar="CODE",
        help="agency recorded in the 884 (default: DLC)",
    )
    parser.add_argument(
        "--generation-uri",
        metavar="URI",
        help="URI of the conversion process, recorded in the 884",
    )

    lookups = parser.add_argument_group(
        "authority lookups",
        "Some fields cannot be built without reading the authority record a URI "
        "names: an lcgft genre form yields a 655 with no tag at all if its "
        "record is not fetched. Lookups are therefore on by default, and go to "
        "id.loc.gov, id.worldcat.org and d-nb.info over HTTPS.",
    )
    lookups.add_argument(
        "--no-authority-lookup",
        dest="authority_lookup",
        action="store_false",
        help="do not dereference any authority URI. Touches no network and "
        "gives repeatable output, at the cost of the fields that need one",
    )
    lookups.add_argument(
        "--delay",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="wait this long between authority requests (default: 0). "
        "Responses are cached and 429s are honoured, so most batches need none",
    )
    lookups.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="give up on an authority request after this long (default: 30)",
    )
    lookups.add_argument(
        "--retries",
        type=int,
        default=3,
        metavar="N",
        help="retry a request the service asks us to repeat this many times "
        "(default: 3)",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"marc-bibframe, bibframe2marc {upstream('bibframe2marc')['tag']}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    rdf = read_input(args.input, "bibframe-marc")
    convert = bibframe_to_marc if args.format == "marc" else bibframe_to_marcxml

    try:
        out = convert(
            rdf,
            format=None if args.input_format == "auto" else args.input_format,
            record_id=args.record_id,
            cat_script=args.cat_script,
            bcp47_inference=args.bcp47_inference,
            generation_datestamp=args.datestamp,
            source_record_id=args.source_record_id,
            conversion_agency=args.conversion_agency,
            generation_uri=args.generation_uri,
            authority_lookup=args.authority_lookup,
            request_delay=args.delay,
            request_timeout=args.timeout,
            max_retries=args.retries,
        )
    except (ValueError, TypeError) as error:
        raise SystemExit(f"bibframe-marc: {error}") from error

    write_output(out, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
