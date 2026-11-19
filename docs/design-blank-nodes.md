# Design: blank nodes instead of minted URIs

## Why

marc2bibframe2 mints `{baseuri}{record id}#{fragment}` URIs for everything MARC
doesn't identify: the Work, Instance, Hubs, Items and headings with no `$0`.
They name nothing. When Blue Core saves them, headings keep their fake URI
(issue #11), and the Work and Instance get a `bf:derivedFrom` pointing at a
placeholder. Given a blank-node Work or Instance, Blue Core mints a URI and
records no `derivedFrom`, which is what we want for MARC imports.

## Goals

- An opt-in mode where nothing minted survives: every minted URI is a blank
  node, Work and Instance included.
- Default output is the classic LC stylesheet output, except that the
  default base becomes `urn:x-marc-bibframe:`, which can't be mistaken for a
  resolvable URI the way `http://example.org/` can.
- No patches to the vendored XSLT, and no regex over fragment names.

## Non-goals

- Changing bluecore_api, the FOLIO task or the `marc2bf` DAG. They adopt the
  option afterwards.
- Making the reverse direction (`bibframe_to_marc`) accept blank-node
  Works and Instances.

## Approaches considered

- **A. Blank everything by default, and fix the consumers** (bounded JSON-LD,
  bibframe2marc, ordering). Rejected: it changes the classic output and
  touches bibframe-json.
- **B. Opt-in blank nodes, using a sentinel base.** Chosen.
- **C. Blank only the headings, and have `save_graph` skip `derivedFrom` for
  the sentinel base.** Rejected: it couples bluecore-models to this package's
  base.

## Design

- `DEFAULT_BASE_URI` becomes `urn:x-marc-bibframe:`, for every function and
  the CLI.
- `marcxml_to_graph(marcxml, *, blank_nodes=False, **kwargs)`. With
  `blank_nodes=True`:
  - every URI starting with `DEFAULT_BASE_URI` becomes a blank node, with all
    its triples kept. A URI that is cited more than once becomes one blank
    node.
  - a `baseuri` other than the default raises `ValueError`.
- `marc_to_graph` passes the keyword through.
- `marcxml_to_jsonld` and `marc_to_jsonld` raise `ValueError` if given
  `blank_nodes=True`. A bounded description needs an `@id` on the Instance and
  the Work. Raising makes every place that does this visible.
- `marcxml_to_rdfxml` doesn't take the option. It stays the stylesheet's own
  output.
- CLI: `--blank-nodes`. It is an error together with `--baseuri`, and with
  `-f rdfxml`, `-f json-ld` or `-f turtle`. Turtle is refused because rdflib's
  Turtle writer can write a list cell twice in these graphs
  (https://github.com/RDFLib/rdflib/issues/3736). A strict `xfail` test,
  `test_rdflib_turtle_writes_a_list_cell_once`, starts failing when the
  installed rdflib has a fix. Since Turtle is the default
  format, `--blank-nodes` needs an explicit `-f nt`, `-f xml` or
  `-f json-ld-expanded`.
- CLI `-f json-ld-expanded` is written by pyld's `from_rdf` rather than
  rdflib's JSON-LD serializer, which drops blank nodes that only refer to
  each other, such as a blank Work and Instance. This is fixed for rdflib 8
  (https://github.com/RDFLib/rdflib/pull/3679), which isn't released yet.
  Dropping the workaround will likely mean requiring rdflib 8. A strict
  `xfail` test, `test_rdflib_json_ld_keeps_a_blank_node_cycle`, starts failing
  when the installed rdflib has the fix.
- README: a short section under "A note on the URIs it mints".

## Tests

- Default output is unchanged apart from the base. The existing tests that
  expect `http://example.org/` expect `urn:x-marc-bibframe:` instead.
- With `blank_nodes=True`:
  - no URI starts with `urn:x-marc-bibframe:`
  - the Work, Instance and agent are blank nodes
  - the agent keeps its label and marcKey
  - an id.loc.gov `$0` heading keeps its URI
  - the blanked graph is isomorphic to the minted graph after the rewrite
- `blank_nodes=True` with a `baseuri` raises.
- The JSON-LD functions with `blank_nodes=True` raise.
- The CLI flag works, and is refused with `--baseuri`, `-f rdfxml`,
  `-f json-ld` and Turtle.

## Consequences

- bluecore_api imports `DEFAULT_BASE_URI` as its `source_base_uri` default, so
  `/marc2bibframe` returns `urn:x-marc-bibframe:` URIs once it upgrades, even
  before it adopts `blank_nodes`.
- Output no longer matches LC's stylesheet run with its own default.
- Anyone serializing a blank-node graph themselves should use N-Triples or
  RDF/XML. bluecore_api serializes with rdflib, so it will need to as well when
  it adopts `blank_nodes`.
- N-Triples that open on a `urn:` subject are now recognised as N-Triples
  when converting back to MARC. Before, they were read as RDF/XML.

## My calls (check these)

- The name: `blank_nodes` / `--blank-nodes`, which reads better as an opt-in
  than `mint_default_uris=False`.
- The blanking stays private in `marcxml_to_graph`, not exported.
- The version goes to 0.4.0, for the new default base and the new public
  keyword. bluecore-airflow-common's
  `<0.4` pin has to move when the DAGs adopt it, which needs a code change
  anyway.
