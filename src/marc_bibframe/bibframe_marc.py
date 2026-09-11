"""Convert BIBFRAME RDF/XML to MARC.

A thin Python wrapper around the Library of Congress bibframe2marc XSLT
(https://github.com/lcnetdev/bibframe2marc), which is vendored in this package.

Unlike marc2bibframe2, bibframe2marc is not published as a stylesheet. Upstream
maintains a set of conversion rules in an XML DSL plus a compiler stylesheet
that turns them into one, and drives the build with xsltproc. Both are vendored
here and the conversion stylesheet is compiled at first use instead, which
takes about fifty milliseconds -- not worth committing a 1.4 MB generated
artifact to avoid.
"""

from __future__ import annotations

import contextlib
import copy
import functools
import time
import urllib.error
import urllib.request
import warnings
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path
from typing import Any

import lxml.etree as ET
import pymarc
import rdflib
from rdflib import Graph

from marc_bibframe import _striping
from marc_bibframe._xslt import (
    COLLECTION_CLOSE,
    COLLECTION_OPEN,
    MARCXML_NS,
    resource_dir,
    xslt_params,
)

__all__ = [
    "DEFAULT_USER_AGENT",
    "FORMATS",
    "AuthorityLookupWarning",
    "bibframe_to_marc",
    "bibframe_to_marcxml",
    "clear_authority_cache",
]

#: Input serializations, keyed the way marc-bibframe's --format keys its output
#: ones, and pointing at rdflib's name for each. ``rdfxml`` is the odd one out
#: in the same way it is on the way out: it goes straight to the stylesheet
#: rather than through a parse into rdflib.
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

_BF = "http://id.loc.gov/ontologies/bibframe/"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

try:
    _VERSION = version("marc-bibframe")
except PackageNotFoundError:  # a source tree with nothing installed
    _VERSION = "unknown"

#: Sent with every authority lookup, so LC can see who is asking.
DEFAULT_USER_AGENT = (
    f"marc-bibframe/{_VERSION} (+https://github.com/blue-core-lod/marc-bibframe)"
)

#: What the stylesheet itself yields for a lookup that found nothing.
_EMPTY_COLLECTION = f'<collection xmlns="{MARCXML_NS}"/>'.encode()

#: Longest we will honour a Retry-After, or back off, before giving up.
_MAX_RETRY_WAIT = 60.0

#: Roots that say the input went the wrong way round. pymarc writes the
#: unnamespaced ones.
_MARCXML_ROOTS = {
    f"{{{MARCXML_NS}}}record",
    f"{{{MARCXML_NS}}}collection",
    "record",
    "collection",
}

_NOT_STRIPED = (
    "this RDF/XML is not striped: bibframe2marc needs a document whose top "
    "level holds exactly one bf:Instance and at most one bf:Work, linked by "
    "bf:instanceOf, which is the shape marc2bibframe2 emits. Leave format "
    "unset, or pass format='xml', to rebuild it through rdflib instead."
)

#: Authority records already fetched, keyed by URL and shared across
#: conversions: the same names and subjects recur constantly across a batch. A
#: None records a lookup that failed and is not worth repeating this process.
_AUTHORITY_CACHE: dict[str, bytes | None] = {}


class AuthorityLookupWarning(UserWarning):
    """An authority record could not be fetched, so some MARC may be missing."""


def clear_authority_cache() -> None:
    """Forget every authority record fetched so far in this process."""
    _AUTHORITY_CACHE.clear()


def _is_remote(url: str) -> bool:
    return url.startswith(("http://", "https://", "ftp://", "ftps://"))


def _retry_after(error: urllib.error.HTTPError, attempt: int) -> float:
    """How long the service asked us to wait, falling back to exponential backoff."""
    header = error.headers.get("Retry-After") if error.headers else None
    if header:
        try:
            return min(max(float(header), 0.0), _MAX_RETRY_WAIT)
        except ValueError:
            pass
        try:
            when = parsedate_to_datetime(header)
        except (TypeError, ValueError):
            when = None
        if when is not None:
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            seconds = (when - datetime.now(UTC)).total_seconds()
            return min(max(seconds, 0.0), _MAX_RETRY_WAIT)
    return min(2.0**attempt, _MAX_RETRY_WAIT)


class _OfflineResolver(ET.Resolver):
    """Answer every remote lookup with an empty record, fetching nothing."""

    # ty: ignore[invalid-method-override]  (lxml-stubs omits the context argument)
    def resolve(self, url: str, pubid: str | None, context: Any) -> Any:
        if _is_remote(url):
            return self.resolve_string(_EMPTY_COLLECTION, context, base_url=url)
        return None


class _AuthorityResolver(ET.Resolver):
    """Fetch the authority records the transform asks for, politely.

    lxml routes ``document()`` through the resolvers of the parser that read the
    stylesheet, so this is where the transform's authority lookups land. libxslt
    cannot make them itself -- libxml2 2.14 dropped its HTTP client -- which is
    also why the vendored compiler is patched to stop assuming that a libxslt
    processor cannot reach HTTPS. Without the patch the transform silently skips
    label, hub, FAST and GND lookups and routes the rest through a legacy SRU
    gateway.
    """

    def __init__(
        self, *, delay: float, timeout: float, max_retries: int, user_agent: str
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent
        #: URLs that could not be fetched during the current conversion. The
        #: resolver is cached along with the transform and so outlives any one
        #: call; bibframe_to_marcxml clears this before each.
        self.failures: list[str] = []
        self._requests = 0

    # ty: ignore[invalid-method-override]  (lxml-stubs omits the context argument)
    def resolve(self, url: str, pubid: str | None, context: Any) -> Any:
        if not _is_remote(url):
            return None
        record = self._fetch(url)
        if record is None:
            self.failures.append(url)
            record = _EMPTY_COLLECTION
        return self.resolve_string(record, context, base_url=url)

    def _fetch(self, url: str) -> bytes | None:
        if url in _AUTHORITY_CACHE:
            return _AUTHORITY_CACHE[url]

        for attempt in range(self.max_retries + 1):
            if self.delay and self._requests:
                time.sleep(self.delay)
            self._requests += 1
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": self.user_agent}
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    record = response.read()
                _AUTHORITY_CACHE[url] = record
                return record
            except urllib.error.HTTPError as error:
                # 429 and 503 are the service asking us to come back later.
                if error.code in (429, 503) and attempt < self.max_retries:
                    time.sleep(_retry_after(error, attempt))
                    continue
                break
            except OSError:  # URLError, timeouts, DNS and connection failures
                if attempt < self.max_retries:
                    time.sleep(min(2.0**attempt, _MAX_RETRY_WAIT))
                    continue
                break

        _AUTHORITY_CACHE[url] = None
        return None


def _rules_manifest(directory: Path) -> ET._Element:
    """The manifest upstream's buildrules.sh writes, built in memory instead."""
    rules = directory / "rules"
    entries = "".join(
        f"<file>rules/{path.name}</file>" for path in sorted(rules.glob("*.xml"))
    )
    manifest = (
        '<rules xmlns="http://www.loc.gov/bf2marc">'
        f"<version>{(rules / 'VERSION').read_text().strip()}</version>"
        f"{entries}</rules>"
    )
    # The <file> hrefs are relative to the manifest, which upstream writes
    # beside the rules directory.
    return ET.fromstring(manifest.encode(), base_url=str(directory / "rules.xml"))


@functools.lru_cache(maxsize=8)
def _transform(
    authority_lookup: bool,
    delay: float,
    timeout: float,
    max_retries: int,
    user_agent: str,
) -> tuple[ET.XSLT, _AuthorityResolver | _OfflineResolver]:
    """Compile the conversion stylesheet out of the vendored rules.

    Cached because it is not free (~50ms) and a batch calls it once per record.
    """
    directory = resource_dir("bf2marc")
    compiler = ET.XSLT(ET.parse(str(directory / "compile.xsl")))
    generated = compiler(_rules_manifest(directory))

    resolver: _AuthorityResolver | _OfflineResolver
    if authority_lookup:
        resolver = _AuthorityResolver(
            delay=delay,
            timeout=timeout,
            max_retries=max_retries,
            user_agent=user_agent,
        )
    else:
        resolver = _OfflineResolver()

    # The resolver belongs on the parser that reads the stylesheet: that is the
    # one lxml consults for document(). huge_tree because the compiled
    # stylesheet runs to about 1.4 MB.
    parser = ET.XMLParser(huge_tree=True)
    parser.resolvers.add(resolver)
    stylesheet = ET.fromstring(
        ET.tostring(generated), parser, base_url=str(directory / "bibframe2marc.xsl")
    )
    return ET.XSLT(stylesheet), resolver


def _sniff(data: bytes) -> str:
    """Guess the serialization from the first character that is not space.

    Only ever has to tell three things apart, since rdflib's Turtle parser
    reads N-Triples too.
    """
    head = data.lstrip().lstrip(b"\xef\xbb\xbf")
    if head.startswith(b"<"):
        # N-Triples opens with a < too, but on a full URI in angle brackets
        # rather than an element name, and an element name cannot hold a "://".
        end = head.find(b">")
        if end > 0 and b"://" in head[1:end]:
            return "ntriples"
        return "rdfxml"
    if head.startswith((b"{", b"[")):
        return "json-ld"
    return "turtle"


def _is_striped(document: ET._Element) -> bool:
    """Does this document already have the shape the stylesheet insists on?"""
    return document.tag == f"{{{_RDF}}}RDF" and any(
        child.tag == f"{{{_BF}}}Instance" for child in document
    )


@contextlib.contextmanager
def _exact_literals():
    """Stop rdflib rewriting typed literals while it parses.

    It normalizes them by default, which turns an xsd:duration of PT00H31M00S
    into PT31M -- and so the 306 the stylesheet builds from it from 003100 into
    31. The switch is global, so this puts it back afterwards. A Graph handed to
    us directly was parsed before we had any say, and keeps whatever it got.
    """
    previous = rdflib.NORMALIZE_LITERALS
    # ty: ignore[invalid-assignment]  (rdflib types its own switch as Literal[True])
    rdflib.NORMALIZE_LITERALS = False
    try:
        yield
    finally:
        rdflib.NORMALIZE_LITERALS = previous


def _graph(data: bytes, rdflib_format: str) -> Graph:
    graph = Graph()
    try:
        with _exact_literals():
            graph.parse(data=data, format=rdflib_format)
    except Exception as error:
        # rdflib's parsers raise all sorts, and none of it says much.
        raise ValueError(
            f"could not read the input as {rdflib_format}: {error}"
        ) from error
    return graph


def _input_descriptions(
    data: str | bytes | Graph, format: str | None
) -> list[ET._Element]:
    """Every BIBFRAME description in the input, ready for the stylesheet."""
    if isinstance(data, Graph):
        return _striping.descriptions(data)

    if isinstance(data, str):
        # Encode first: lxml refuses a str carrying an encoding declaration.
        data = data.encode("utf-8")

    guessed = format is None
    if guessed:
        # A MARC21 leader opens with the record length in five digits. Catch it
        # here: rdflib's Turtle parser would otherwise log a wall of syntax
        # errors before failing.
        if data[:5].isdigit():
            raise ValueError(
                "this is binary MARC21, not BIBFRAME. marc_to_graph and the "
                "marc-bibframe command convert that direction"
            )
        format = _sniff(data)

    try:
        rdflib_format = FORMATS[format]
    except KeyError:
        raise ValueError(
            f"unknown format {format!r}; expected one of {', '.join(sorted(FORMATS))}"
        ) from None

    if rdflib_format is None:
        document = ET.fromstring(data)
        if _is_striped(document):
            return _descriptions(document)
        if document.tag in _MARCXML_ROOTS:
            # The likeliest mistake, with two sibling commands about.
            raise ValueError(
                "this is MARCXML, not BIBFRAME. marc_to_graph and the "
                "marc-bibframe command convert that direction"
            )
        if guessed:
            # Striped RDF/XML is the cheap way in, but plenty of RDF/XML is
            # not striped. Rebuild it rather than refuse it.
            return _striping.descriptions(_graph(data, "xml"))
        raise ValueError(_NOT_STRIPED)

    return _striping.descriptions(_graph(data, rdflib_format))


def _descriptions(root: ET._Element) -> list[ET._Element]:
    """Split an RDF/XML document into one striped description per Instance.

    The stylesheet insists on a single top-level bf:Instance, but marc2bibframe2
    emits a Work and an Instance for every record it is given, so anything
    converted from more than one MARC record has to be taken apart again. Each
    Instance goes back out with the Work its bf:instanceOf names.
    """
    instances = [child for child in root if child.tag == f"{{{_BF}}}Instance"]
    if len(instances) < 2:
        return [root]

    works = {
        child.get(f"{{{_RDF}}}about"): child
        for child in root
        if child.tag == f"{{{_BF}}}Work"
    }

    split = []
    for instance in instances:
        description = ET.Element(f"{{{_RDF}}}RDF")
        instance_of = instance.find(f"{{{_BF}}}instanceOf")
        work = (
            works.get(instance_of.get(f"{{{_RDF}}}resource"))
            if instance_of is not None
            else None
        )
        # Work first, then Instance: the order marc2bibframe2 emits, and the
        # order _striping builds. The two 758s come out in that order, so all
        # three routes into the stylesheet have to agree on it.
        if work is not None:
            description.append(copy.deepcopy(work))
        description.append(copy.deepcopy(instance))
        split.append(description)
    return split


def bibframe_to_marcxml(
    rdf: str | bytes | Graph,
    *,
    format: str | None = None,
    record_id: str | None = None,
    cat_script: str | None = None,
    bcp47_inference: bool | None = None,
    generation_datestamp: str | None = None,
    source_record_id: str | None = None,
    conversion_agency: str | None = None,
    generation_uri: str | None = None,
    authority_lookup: bool = True,
    request_delay: float = 0.0,
    request_timeout: float = 30.0,
    max_retries: int = 3,
    user_agent: str = DEFAULT_USER_AGENT,
) -> bytes:
    """Transform BIBFRAME RDF into a MARCXML ``<collection>``.

    Takes RDF/XML, Turtle, N-Triples, JSON-LD or an ``rdflib.Graph``, and makes
    one MARC record per ``bf:Instance`` it finds.

    format
        One of :data:`FORMATS`, using the same names :func:`marcxml_to_rdfxml`
        writes. Guessed from the input when unset, which is usually what you
        want. ``rdfxml`` hands the document straight to the stylesheet, which
        needs it striped already -- one top-level ``bf:Instance`` and at most
        one top-level ``bf:Work``, the shape :func:`marcxml_to_rdfxml` emits --
        and is the cheapest route in. Anything else is parsed into a graph and
        restriped, which any BIBFRAME survives but costs a parse and a rebuild.
    record_id
        Value for the 001. Left unset, each record's id comes from its own
        ``bf:Local`` identifier, or a generated id if it has none. Cannot be
        given for input holding more than one description.
    cat_script
        Default cataloguing script for ``xml:lang`` attributes, ``Latn`` by
        default.
    bcp47_inference
        Omit a BCP-47 script subtag when the language implies it. On by default.
    generation_datestamp
        Override the conversion timestamp, which otherwise defaults to now. Set
        it, with ``authority_lookup=False``, to make output reproducible.
    source_record_id, conversion_agency, generation_uri
        Recorded in the 884 conversion note. The agency defaults to ``DLC``.
    authority_lookup
        Dereference the authority URIs in the description, on by default,
        because some fields cannot be built without them -- an lcgft genre form
        yields a 655 with no tag at all if its authority record is not read.
        Lookups go to id.loc.gov (also id.worldcat.org and d-nb.info), are
        cached for the life of the process, and back off when asked to. Turn
        them off for conversion that touches no network and does not vary.
    request_delay
        Seconds to wait between authority requests. Zero by default: responses
        are cached and 429s are honoured, so most batches need no throttling.
    request_timeout, max_retries, user_agent
        How long to wait on each authority request, how many times to retry one
        the service asks us to repeat, and how to identify ourselves.

    Raises ValueError if the input is not striped RDF/XML, and warns with
    :class:`AuthorityLookupWarning` if a lookup failed, since the MARC is then
    quietly incomplete rather than wrong in any visible way.
    """
    descriptions = _input_descriptions(rdf, format)
    if record_id is not None and len(descriptions) > 1:
        raise ValueError(
            f"record_id={record_id!r} cannot apply to {len(descriptions)} "
            "descriptions at once; convert them one at a time, or leave it unset "
            "to take each record's id from its own bf:Local identifier"
        )

    transform, resolver = _transform(
        authority_lookup, request_delay, request_timeout, max_retries, user_agent
    )
    params = xslt_params(
        pRecordId=record_id,
        pCatScript=cat_script,
        bcp47inferrence=bcp47_inference,
        pGenerationDatestamp=generation_datestamp,
        pSourceRecordId=source_record_id,
        pConversionAgency=conversion_agency,
        pGenerationUri=generation_uri,
        pHttpsAvailable=authority_lookup,
    )

    if isinstance(resolver, _AuthorityResolver):
        resolver.failures.clear()

    collection = ET.fromstring(COLLECTION_OPEN + COLLECTION_CLOSE)
    for description in descriptions:
        try:
            result = transform(description, **params)
        except ET.XSLTApplyError as error:
            # The stylesheet rejects anything unstriped with an xsl:message,
            # which arrives as an opaque one-liner ("Invalid document: no RDF
            # root element"). Say what shape was wanted.
            detail = str(error).strip()
            unstriped = "Invalid document" in detail or "Instance" in detail
            raise ValueError(
                f"{detail}\n\n{_NOT_STRIPED}" if unstriped else detail
            ) from error
        collection.append(result.getroot())

    if isinstance(resolver, _AuthorityResolver) and resolver.failures:
        shown = ", ".join(resolver.failures[:3])
        if len(resolver.failures) > 3:
            shown += f", and {len(resolver.failures) - 3} more"
        warnings.warn(
            f"{len(resolver.failures)} authority lookup(s) failed, so the MARC "
            f"may be missing fields that depend on them: {shown}",
            AuthorityLookupWarning,
            stacklevel=2,
        )

    return ET.tostring(
        collection, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )


def bibframe_to_marc(rdf: str | bytes | Graph, **kwargs: Any) -> bytes:
    """Convert BIBFRAME RDF straight to binary MARC21.

    Takes the same keyword arguments as :func:`bibframe_to_marcxml`.
    """
    marcxml = bibframe_to_marcxml(rdf, **kwargs)
    return b"".join(
        record.as_marc() for record in pymarc.parse_xml_to_array(BytesIO(marcxml))
    )
