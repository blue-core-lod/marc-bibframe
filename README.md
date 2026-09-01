# marc-bibframe

[![Test](https://github.com/blue-core-lod/marc-bibframe/actions/workflows/test.yml/badge.svg)](https://github.com/blue-core-lod/marc-bibframe/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/marc-bibframe)](https://pypi.org/project/marc-bibframe/)

Convert MARC records to BIBFRAME RDF in Python, using the Library of Congress
[marc2bibframe2](https://github.com/lcnetdev/marc2bibframe2) XSLT.

The stylesheet is vendored in this package, so there is nothing to install
alongside it and no Java or Saxon involved, just `lxml`, `pymarc` and
`rdflib`.

## Install

```
pip install marc-bibframe
```

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

## Keeping up with upstream

`src/marc_bibframe/xsl/` is a copy of the LC stylesheets — see
[`UPSTREAM`](src/marc_bibframe/xsl/UPSTREAM) for the tag and commit. Local
changes are not edited in place; they live as patches in
[`patches/`](patches/) and are reapplied on every re-vendor:

```
./scripts/vendor.py v3.2.0
```

If a patch stops applying the script says so and stops, which is usually the
signal that it was fixed upstream and can be deleted. The aim is to keep
`patches/` empty; anything in there should also be reported to LC.

The stylesheets are [CC0](src/marc_bibframe/xsl/LICENSE). This wrapper is
[MIT](LICENSE).

## Reproducible output

The transform stamps the current time into the work's admin metadata.
`generation_datestamp` (`--datestamp`) overrides it, which makes the RDF/XML
byte-for-byte reproducible. The other serializations still vary between runs:
rdflib mints fresh blank node labels every time it serializes.

## Development

```
uv sync
uv run pytest
```
