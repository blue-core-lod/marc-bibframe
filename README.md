# marc-bibframe

[![Test](https://github.com/blue-core-lod/marc-bibframe/actions/workflows/test.yml/badge.svg)](https://github.com/blue-core-lod/marc-bibframe/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/marc-bibframe)](https://pypi.org/project/marc-bibframe/)

Convert between MARC and BIBFRAME RDF in Python, using the Library of Congress
[marc2bibframe2](https://github.com/lcnetdev/marc2bibframe2) and
[bibframe2marc](https://github.com/lcnetdev/bibframe2marc) XSLTs.

Both stylesheets are vendored in this package, so there is nothing to install
alongside them and no Java, Saxon or xsltproc involved, just `lxml`, `pymarc`
and `rdflib`.

## Install

```
pip install marc-bibframe
```

# MARC to BIBFRAME

## Command line

You can use it from the command line:

```
$ marc-bibframe record.mrc
$ marc-bibframe record.xml --format json-ld --baseuri https://example.edu/catalog/
$ yaz-marcdump -o marcxml big.mrc | marc-bibframe -f nt -o big.nt
```

Binary MARC21 and MARCXML are both accepted and told apart by their content,
so there is no flag for it. With no filename it reads standard input.

`--format` takes `turtle` (the default), `json-ld`, `ntriples`, `xml`, or
`rdfxml`. The last is the stylesheet's own output passed through without a
parse into rdflib, which is faster and keeps the transform's exact shape.

`marc-bibframe --help` lists the stylesheet parameters, which are also
available as flags.

## Use as a library

Or you can use it as a function in your own Python programs:

```python
from marc_bibframe import marc_to_graph

with open("record.mrc", "rb") as fh:
    graph = marc_to_graph(fh, baseuri="https://example.edu/catalog/")

print(graph.serialize(format="turtle"))
```

MARCXML is accepted directly, and RDF/XML is available if you would rather not
pay for a parse into an rdflib.Graph:

```python
from marc_bibframe import marc_to_marcxml, marcxml_to_graph, marcxml_to_rdfxml

marcxml = marc_to_marcxml(open("record.mrc", "rb").read())
graph = marcxml_to_graph(marcxml)
rdfxml = marcxml_to_rdfxml(marcxml)
```

All four functions accept the stylesheet's parameters as keyword arguments —
`baseuri`, `idfield`, `idsource`, `localfields`, `bcp47_inference` and
`generation_datestamp`. See the docstring on `marcxml_to_rdfxml` for what each
one does.

## A note on the URIs it mints

MARC does not identify most of what it describes, so the transform invents
URIs for them, built from `baseuri` and the record's own id:

```
https://example.edu/catalog/99123456#Work
https://example.edu/catalog/99123456#Instance
https://example.edu/catalog/99123456#Agent100-3
https://example.edu/catalog/99123456#Topic650-5
```

These are **not** authority URIs. They are scoped to the record they came
from, so two records describing the same person produce two different agent
URIs. If you need them reconciled against an authority (LC, Wikidata, your
own store) that happens after this library hands you the graph.

For the same reason the default `baseuri` is `http://example.org/`, matching
the stylesheet's own. Pick something under your control, and prefer a
namespace that cannot be mistaken for an authority's: minting
`http://id.loc.gov/resources/99123456#Agent100-3` produces URIs that look like
LC's but are not.

# BIBFRAME to MARC

## Command line

```
$ bibframe-marc description.ttl
$ bibframe-marc work.jsonld -f marc -o record.mrc
$ marc-bibframe record.mrc -f rdfxml | bibframe-marc --record-id 99123456
```

`-f/--format` takes `marcxml` (the default) or `marc` for binary MARC21. Output
is always a MARCXML `<collection>`, even of one record. With no filename it
reads standard input.

`-i/--input-format` takes the same names `marc-bibframe --format` writes —
`turtle`, `json-ld`, `ntriples`, `xml`, `rdfxml` — so whatever comes out of one
command goes into the other. It defaults to `auto`, which works out the
serialization from the content, so you rarely need it.

## Use as a library

```python
from marc_bibframe import bibframe_to_marc, bibframe_to_marcxml

marcxml = bibframe_to_marcxml(open("description.xml", "rb").read())
marc21 = bibframe_to_marc(open("description.xml", "rb").read())
```

Turtle, N-Triples, JSON-LD, RDF/XML and an `rdflib.Graph` are all accepted, and
told apart by their content unless you say otherwise:

```python
from rdflib import Graph

graph = Graph()
graph.parse("description.ttl")
marcxml = bibframe_to_marcxml(graph)

# or name the serialization, using marc-bibframe's own names for them
marcxml = bibframe_to_marcxml(turtle, format="turtle")
```

One MARC record comes out per `bf:Instance`, so a graph describing several
becomes a collection of several.

Both functions accept the stylesheet's parameters as keyword arguments —
`record_id`, `cat_script`, `bcp47_inference`, `generation_datestamp`,
`source_record_id`, `conversion_agency` and `generation_uri` — plus the lookup
controls below. See the docstring on `bibframe_to_marcxml` for what each one
does.

## Striping

bibframe2marc converts one "description" at a time, which LC's
[design notes](https://github.com/lcnetdev/bibframe2marc/blob/master/doc/design.md)
define as a graph with exactly one top-level `bf:Instance` and zero or one
top-level `bf:Work`, linked by `bf:instanceOf` or `bf:hasInstance`, serialized
as *striped* RDF/XML — property and class elements alternating, each object
nested inside the property that reaches it.

That is the shape marc2bibframe2 emits, so its output goes straight to the
stylesheet untouched; that is what `format="rdfxml"` asks for, and it is the
cheapest way in. Nothing else has that shape — notably, serializing the very
same graph through rdflib does not — so any other input is parsed into a graph
and rebuilt, which is the job LC's Perl library
[Biblio::BF2MARC](https://github.com/lcnetdev/biblio-bf2marc) does.

### How faithful is it?

Measured against the 151 BIBFRAME descriptions in
[LC's own bibframe2marc test data](https://github.com/lcnetdev/bibframe2marc/tree/master/rules/test/data),
comparing each one converted directly with the same bytes parsed into a graph
and rebuilt:

| | files |
| --- | --- |
| identical, field for field and in the same order | 121 |
| same fields, some in a different order | 13 |
| some field content differs | 14 |
| not valid RDF/XML, so no graph to rebuild from | 2 |
| no `bf:Instance`, so no record either way | 1 |

Three fixable causes turned up on the way, each now pinned by a test in
`tests/fixtures/descriptions/`: `rdf:parseType="Collection"` lists like
`madsrdf:elementList` have to go back out as collections or a heading loses its
`$a`; a node typed both `bf:Hub` and `bf:Arrangement` has to be named after the
general class or the 240 never fires; and rdflib normalizes typed literals as it
parses unless told not to, which turns an `xsd:duration` of `PT00H31M00S` into
`PT31M` and a 306 of `003100` into `31`.

The rest is the nature of the thing. **An RDF graph does not record the order of
repeated properties**, and some rules read that order: which of several
languages lands in the 008, the sequence of instruments in a 382, the order of
`$b`s in a 264. Going through a graph loses it, and no amount of care in the
rebuilding brings it back. Order is preserved inside `rdf:parseType="Collection"`
lists, because there it is part of the data.

So if what you have is marc2bibframe2's own RDF/XML, hand it over as `rdfxml`
and none of this arises. The rebuild is for graphs that arrive any other way.

Two things it will not do. A graph with no `bf:Instance` has no record in it:

```python
ValueError: no bf:Instance in the graph, so there is nothing to convert
```

And `format="rdfxml"` means what it says, so unstriped RDF/XML under that flag
is an error rather than a silent reparse — leave `format` unset if you want it
rebuilt. That strictness has a second use: the stylesheet only ever does XPath
matching, so it happily converts RDF/XML that is not actually valid RDF, which
rdflib would refuse outright. Two of LC's own test descriptions are like that.

## Round trips

Converting MARC to BIBFRAME and back gives you a record with two 758 fields in
it, holding the URIs of the Work and Instance the MARC came from. That is
deliberate on bibframe2marc's part, but it changes how marc2bibframe2 reads the
record on a second pass: a 758 saying `$4 instanceOf` names an existing Work,
so no Work is generated and the Instance comes out typed
`bflc:SecondaryInstance`. For the verne test record that is 14 triples rather
than 74.

Both stylesheets are behaving as designed — the record now says "this describes
that existing entity" rather than describing one itself. If what you want is a
full description again, drop the 758s before converting back:

```python
for field in record.get_fields("758"):
    record.remove_field(field)
```

## Authority lookups

Some MARC fields cannot be built without reading the authority record a URI
names. The genre form in a record converted from `655 _7 $a Fiction $2 lcgft`
comes back out as a `<datafield>` with **no tag at all** if its authority
record is not fetched, because the tag depends on what kind of thing the
authority says it is.

LC's own test suite takes the same view. Its `100-auth.xml` case is a bare
`bf:Agent rdf:about="http://id.loc.gov/authorities/names/n79022941"` with no
inline data, and the expectations ask for `$a Andersen, H. C.`, `$q (Hans
Christian),` and `$d 1805-1875` — which can only come from dereferencing it.
Twenty of their expectations go from failing to passing when lookups are on.

So lookups are on by default. They go over HTTPS to id.loc.gov (also
id.worldcat.org and d-nb.info), are cached for the life of the process — the
same names and subjects recur constantly across a batch — and honour a
`Retry-After` on a 429 or 503, backing off exponentially when there is no such
header. A lookup that fails is reported with an `AuthorityLookupWarning`
rather than passing silently, since the MARC is then incomplete in a way
nothing else would show you:

```python
AuthorityLookupWarning: 1 authority lookup(s) failed, so the MARC may be
missing fields that depend on them: https://id.loc.gov/authorities/...
```

To convert without touching the network, at the cost of those fields:

```
$ bibframe-marc description.xml --no-authority-lookup
```

```python
bibframe_to_marcxml(rdfxml, authority_lookup=False)
```

`--delay SECONDS` (`request_delay`) waits between requests. It is zero by
default: responses are cached and 429s are honoured, so most batches need no
throttling. `--timeout` and `--retries` are there too, and `user_agent`
identifies this package to LC.

One wrinkle worth knowing: upstream assumes a libxslt processor cannot reach
HTTPS, and so skips label, hub, FAST and GND lookups outright and routes the
rest through a legacy SRU gateway. That is true of libxslt alone — and libxml2
2.14 dropped its HTTP client entirely — but not of libxslt embedded in a
program that resolves URIs for it, which is what happens here. The patch in
[`patches/bibframe2marc/`](patches/bibframe2marc/) adds a `pHttpsAvailable`
parameter so the full lookup path can be used. It defaults to upstream's own
behaviour, and has been written to be reportable to LC.

# Keeping up with upstream

Each stylesheet is vendored under `src/marc_bibframe/`, with an `UPSTREAM` file
recording the tag and commit:

| | vendored in | upstream |
| --- | --- | --- |
| MARC to BIBFRAME | [`xsl/`](src/marc_bibframe/xsl/UPSTREAM) | [marc2bibframe2](https://github.com/lcnetdev/marc2bibframe2) |
| BIBFRAME to MARC | [`bf2marc/`](src/marc_bibframe/bf2marc/UPSTREAM) | [bibframe2marc](https://github.com/lcnetdev/bibframe2marc) |

Local changes are not edited in place; they live as patches in
[`patches/`](patches/), one directory per stylesheet, and are reapplied on
every re-vendor:

```
./scripts/vendor.py marc2bibframe2 v3.2.0
./scripts/vendor.py bibframe2marc v3.2.0
```

If a patch stops applying the script says so and stops, which is usually the
signal that it was fixed upstream and can be deleted. The aim is to keep
`patches/` empty; anything in there should also be reported to LC. (The
`pHttpsAvailable` patch described above is the exception that will stay until
LC takes it or does something equivalent.)

The test suite checks each vendored tag against LC's latest release and fails
when there is a newer one, with the command to run. It skips rather than fails
if the GitHub API is unreachable.

bibframe2marc is a little different: LC does not publish its conversion
stylesheet, only a set of rules in an XML DSL plus a compiler stylesheet that
turns them into one, built with xsltproc and a Makefile. Both are vendored
here and the conversion stylesheet is compiled by `lxml` at first use, which
takes about fifty milliseconds — not worth committing a 1.4 MB generated
artifact to avoid. Patches therefore target the rules and the compiler, which
is what LC maintains.

The stylesheets are CC0 ([marc2bibframe2](src/marc_bibframe/xsl/LICENSE),
[bibframe2marc](src/marc_bibframe/bf2marc/LICENSE)). This wrapper is
[MIT](LICENSE).

# Reproducible output

Both transforms stamp the current time into their output — the work's admin
metadata one way, the 005 and 884 the other. `generation_datestamp`
(`--datestamp`) overrides it.

Going to BIBFRAME that makes the RDF/XML byte-for-byte reproducible; the other
serializations still vary between runs, as rdflib mints fresh blank node labels
every time it serializes. Coming back to MARC you also want
`--no-authority-lookup`, since otherwise the output depends on what id.loc.gov
says today.

# Development

```
uv sync
uv run pytest
```

Tests are offline: authority lookups are stubbed, and a guard turns an
unexpected network call into a failure rather than a slow pass. The one test
that converts against the live id.loc.gov is deselected by default.

```
uv run pytest -m live
```
