# Blank Nodes Instead of Minted URIs: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `urn:x-marc-bibframe:` the default base, and add an opt-in
`blank_nodes=True` that turns every minted URI into a blank node.

**Architecture:** The stylesheet mints every URI as `{baseuri}{record id}#…`.
With the base fixed to a URN that nothing real is under, `marcxml_to_graph`
can find every minted URI with `startswith` and swap each one for a blank
node. The JSON-LD functions refuse the option, because a bounded description
needs identities.

**Tech Stack:** Python, rdflib, lxml, pytest, uv, ruff, ty.

**Spec:** `docs/design-blank-nodes.md`

## Global Constraints

- `DEFAULT_BASE_URI = "urn:x-marc-bibframe:"`, with the trailing colon.
- The keyword is `blank_nodes: bool = False` and the CLI flag is
  `--blank-nodes`.
- No changes under `src/marc_bibframe/xsl/` or `patches/`. `./scripts/vendor.py --check` must still pass.
- The URIs to blank are found with a plain `startswith(DEFAULT_BASE_URI)`, not
  a regex.
- `marcxml_to_rdfxml` doesn't take the option.
- The checks are CI's: `uv run ruff format --diff`, `uv run ruff check`,
  `uv run ty check`, `uv run pytest`, `uv run ./scripts/vendor.py --check`.
- Don't add lint suppressions.

## Review Focus

- `blank_nodes=True` with `baseuri=None` must raise. `xslt_params` drops
  `None`, so the stylesheet would otherwise fall back to `http://example.org/`
  and nothing would get blanked. The test is in Task 2.
- In a multi-record collection, each Instance must keep its own Work and not
  be merged with another record's. The test is in Task 2.
- Binary MARC through `marc_to_graph(blank_nodes=True)` must work. The test
  is in Task 2.
- `--blank-nodes -f json-ld-expanded` must work, since only the bounded
  `json-ld` is refused. The test is in Task 3.
- Two runs with a pinned datestamp must give isomorphic graphs. The test is
  in Task 2.

---

### Task 1: URN default base

**Files:**
- Modify: `src/marc_bibframe/__init__.py`, the `DEFAULT_BASE_URI` constant
  and the comment above it
- Modify: `README.md`, the paragraph "For the same reason the default
  `baseuri` is `http://example.org/`…"
- Modify: `tests/test_marc_bibframe.py`, `tests/test_jsonld.py:48,58` and
  `tests/test_cli.py:48,49,78`, which expect `http://example.org/`

**Interfaces:**
- Produces: `DEFAULT_BASE_URI == "urn:x-marc-bibframe:"`

- [ ] **Step 1: Change the default-base test to the new value**

In `tests/test_marc_bibframe.py`, replace
`test_baseuri_defaults_to_the_stylesheet_default` with:

```python
def test_baseuri_defaults_to_a_urn(verne_marcxml):
    graph = marcxml_to_graph(verne_marcxml)
    assert DEFAULT_BASE_URI == "urn:x-marc-bibframe:"
    assert str(agent(graph)).startswith("urn:x-marc-bibframe:99123456#")
```

- [ ] **Step 2: Run it and check that it fails**

Run: `uv run pytest tests/test_marc_bibframe.py::test_baseuri_defaults_to_a_urn -v`
Expected: FAIL, because `DEFAULT_BASE_URI` is still `http://example.org/`.

- [ ] **Step 3: Set `DEFAULT_BASE_URI = "urn:x-marc-bibframe:"`**

Update the comment above it: minted URIs name nothing, so the base is a URN
that can't be mistaken for a resolvable one. Rewrite the README paragraph to
match: the default is `urn:x-marc-bibframe:`, not the stylesheet's own
`http://example.org/`, for that reason. Keep the advice to pick a base you
control.

- [ ] **Step 4: Update the tests that expect example.org**

Change `http://example.org/99123456#…` to `urn:x-marc-bibframe:99123456#…` in
`tests/test_jsonld.py:48,58` and `tests/test_cli.py:48,49,78`.

- [ ] **Step 5: Run the CI checks**

Run them as listed in Global Constraints.
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/marc_bibframe/__init__.py README.md tests/
git commit -m "Default the base for minted URIs to urn:x-marc-bibframe:"
```

### Task 2: `blank_nodes` on `marcxml_to_graph`

**Files:**
- Create: `tests/fixtures/headings.xml`, taken from PR #15 with
  `git show pr15:tests/fixtures/headings.xml`. If the `pr15` ref isn't there,
  run `git fetch origin pull/15/head:pr15` first.
- Create: `tests/test_blank_nodes.py`
- Modify: `tests/conftest.py`, to add a `headings_marcxml` fixture that reads
  it
- Modify: `src/marc_bibframe/__init__.py`, for `marcxml_to_graph`, a new
  private `_blank_minted_uris`, and the `marc_to_graph` docstring

**Interfaces:**
- Consumes: `DEFAULT_BASE_URI` from Task 1
- Produces: `marcxml_to_graph(marcxml: str | bytes, *, blank_nodes: bool = False, **kwargs: Any) -> Graph`.
  It raises `ValueError` whose message contains `blank_nodes` when
  `blank_nodes=True` and `kwargs.get("baseuri", DEFAULT_BASE_URI) != DEFAULT_BASE_URI`.
  `marc_to_graph` passes the keyword through `**kwargs` unchanged.

- [ ] **Step 1: Write the failing tests in `tests/test_blank_nodes.py`**

Use `STAMP = "2026-09-01T00:00:00"`, and a helper
`blank(marcxml, **kw)` that returns
`marcxml_to_graph(marcxml, blank_nodes=True, generation_datestamp=STAMP, **kw)`.

- `test_no_minted_uri_survives(headings_marcxml)`: no node in
  `graph.all_nodes()` is a `URIRef` starting with `DEFAULT_BASE_URI`.
- `test_work_and_instance_are_blank(headings_marcxml)`: every subject of
  `rdf:type bf:Work` and of `rdf:type bf:Instance` is a `BNode`. The one
  Instance's `bf:instanceOf` is one of those Works.
- `test_headings_keep_their_description(headings_marcxml)`:
  - some `BNode` has an `rdfs:label` containing `"Imaginary wars and battles"`
  - the `bf:Person` with an `rdfs:label` containing `"Argus"` is a `BNode`
    with a `bflc:marcKey`
- `test_a_heading_with_an_id_keeps_it(headings_marcxml)`:
  `URIRef("http://id.loc.gov/authorities/subjects/sh85021262")` is in
  `graph.all_nodes()`.
- `test_no_triples_are_lost(headings_marcxml)`:
  `len(blank(x)) == len(marcxml_to_graph(x, generation_datestamp=STAMP))`.
- `test_runs_are_isomorphic(headings_marcxml)`:
  `isomorphic(blank(x), blank(x))`.
- `test_each_record_keeps_its_own_work(two_record_marcxml)`: there are two
  Instances, and their `bf:instanceOf` values are two different `BNode`s.
- `test_binary_marc(verne_marc)`:
  `marc_to_graph(verne_marc, blank_nodes=True)` has a `bf:Instance` that is a
  `BNode`.
- `test_a_baseuri_is_refused(verne_marcxml, baseuri)`, parametrized over
  `"https://example.edu/c/"` and `None`:
  `pytest.raises(ValueError, match="blank_nodes")`.
- `test_the_default_baseuri_is_allowed(verne_marcxml)`:
  `blank(verne_marcxml, baseuri=DEFAULT_BASE_URI)` doesn't raise.
- `test_minting_is_still_the_default(verne_marcxml)`: in
  `marcxml_to_graph(verne_marcxml)`, the `bf:Instance` is
  `URIRef("urn:x-marc-bibframe:99123456#Instance")`.

- [ ] **Step 2: Run them and check that they fail**

Run: `uv run pytest tests/test_blank_nodes.py -v`
Expected: every test fails with `TypeError` (an unexpected keyword
`blank_nodes` reaches `marcxml_to_rdfxml`), except
`test_minting_is_still_the_default` and `test_no_triples_are_lost`, which
pass.

- [ ] **Step 3: Implement it**

- `marcxml_to_graph` checks `baseuri` first, then parses. If
  `blank_nodes` is set, it calls `_blank_minted_uris(graph)`.
- `_blank_minted_uris(graph: Graph) -> None` maps each `URIRef` that starts
  with `DEFAULT_BASE_URI`, as subject or object, to one `BNode`, keeping a
  dict so that repeated citations share it. It rewrites triples in place.
- Document `blank_nodes` in the `marcxml_to_graph` docstring.
- Point the docstrings of `marc_to_graph`, `marcxml_to_jsonld` and
  `marc_to_jsonld` at `marcxml_to_graph` for the keywords.

- [ ] **Step 4: Run the CI checks**

Run them as listed in Global Constraints.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/marc_bibframe/__init__.py tests/
git commit -m "Add blank_nodes to describe minted resources as blank nodes"
```

### Task 3: JSON-LD refusal, CLI flag, README, version

**Files:**
- Modify: `src/marc_bibframe/__init__.py`, for `marcxml_to_jsonld`
- Modify: `src/marc_bibframe/cli.py`, for `parse_args` and `main`
- Modify: `README.md`, under "A note on the URIs it mints"
- Modify: `pyproject.toml`, to change `version` to `"0.4.0"`, and `uv.lock`
  with `uv lock`
- Test: `tests/test_jsonld.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `marcxml_to_graph(..., blank_nodes=...)` from Task 2
- Produces: `marcxml_to_jsonld` raises `ValueError` whose message contains
  `bounded` when `kwargs.get("blank_nodes")` is truthy. `marc_to_jsonld`
  inherits that.

- [ ] **Step 1: Write the failing tests**

In `tests/test_jsonld.py`:
- `test_blank_nodes_are_refused(verne_marcxml, verne_marc)`: both
  `marcxml_to_jsonld(verne_marcxml, blank_nodes=True)` and
  `marc_to_jsonld(verne_marc, blank_nodes=True)` raise `ValueError` matching
  `"bounded"`.

In `tests/test_cli.py`, using its `run(capsys, *args)` helper:
- `test_blank_nodes`: `run(capsys, VERNE_XML, "--blank-nodes", "-f", "nt")`
  contains `"_:"` and does not contain `"urn:x-marc-bibframe:"`.
- `test_blank_nodes_as_expanded_json_ld`: with `-f json-ld-expanded`, the
  output contains `'"@id": "_:'` and not `"urn:x-marc-bibframe:"`.
- `test_blank_nodes_is_refused_with(capsys, extra)`, parametrized over
  `["-f", "rdfxml"]`, `["-f", "json-ld"]` and `["-b", "https://example.edu/c/"]`:
  `pytest.raises(SystemExit)`, with `"marc-bibframe:"` in `str(excinfo.value)`.

- [ ] **Step 2: Run them and check that they fail**

Run: `uv run pytest tests/test_jsonld.py tests/test_cli.py -k blank -v`
Expected: FAIL. The JSON-LD functions don't raise yet, and argparse rejects
`--blank-nodes` with exit code 2.

- [ ] **Step 3: Implement it**

- In `marcxml_to_jsonld`, raise before converting: a bounded description
  needs an `@id` on the Instance and the Work, so serialize
  `marcxml_to_graph(..., blank_nodes=True)` yourself instead.
- In `cli.py`, add `--blank-nodes` (`store_true`), with help text saying that
  it describes the resources MARC doesn't identify as blank nodes, and that it
  can't be combined with `--baseuri`, `-f rdfxml` or `-f json-ld`.
- In `main`, refuse `-f rdfxml` with
  `SystemExit("marc-bibframe: --blank-nodes needs a format rdflib writes, not rdfxml")`.
  Pass `blank_nodes=args.blank_nodes` to `marcxml_to_jsonld` and to
  `marcxml_to_graph`, and turn a `ValueError` from either into
  `SystemExit(f"marc-bibframe: {error}")`.
- In the README, add a paragraph under "A note on the URIs it mints" saying
  that `blank_nodes=True` (`--blank-nodes`) describes all of these as blank
  nodes, for stores like Blue Core that mint their own URIs. Note that the
  bounded JSON-LD functions and `-f rdfxml` refuse it.
- Set the version to `0.4.0` and run `uv lock`.

- [ ] **Step 4: Run the CI checks**

Run them as listed in Global Constraints.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/marc_bibframe/ README.md pyproject.toml uv.lock tests/
git commit -m "Refuse blank_nodes for bounded JSON-LD and add --blank-nodes"
```
