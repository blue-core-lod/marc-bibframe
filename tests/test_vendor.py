"""Does everything still agree on which stylesheets are vendored and where?

The stylesheet inventory used to be written out four times -- in the runtime,
in scripts/vendor.py, in tests/test_upstream.py and in shell in each of the two
workflows. That drifted: the publish workflow kept calling vendor.py with the
one-stylesheet argument list it had before bibframe2marc was added, and because
that step only runs on a release, nothing noticed until v0.3.0 failed to ship.

So these tests hold the copies that remain to each other, and hold both
workflows to calling the script rather than driving it by hand.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from marc_bibframe._xslt import STYLESHEETS as RUNTIME_STYLESHEETS

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "marc_bibframe"
WORKFLOWS = ROOT / ".github" / "workflows"


def load_vendor_script():
    """scripts/vendor.py, which is deliberately not importable as a package.

    It stands alone so it can run before the package is installed, which means
    a test is the only place the two inventories can be compared.
    """
    spec = importlib.util.spec_from_file_location(
        "vendor", ROOT / "scripts" / "vendor.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Its Stylesheet dataclass resolves annotations through sys.modules, which
    # a module built straight from a spec is not in yet.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


vendor = load_vendor_script()


def test_script_and_runtime_agree_on_stylesheets():
    """vendor.py writes the directories the runtime reads."""
    assert {name: s.target for name, s in vendor.STYLESHEETS.items()} == (
        RUNTIME_STYLESHEETS
    )


def test_every_vendored_directory_is_registered():
    """A directory with an UPSTREAM file is a vendored stylesheet.

    Vendoring one by hand without registering it leaves it out of the --check
    run, which is exactly the gap that lets a hand-edit reach PyPI.
    """
    vendored = {path.parent.name for path in PACKAGE.glob("*/UPSTREAM")}
    assert vendored == set(RUNTIME_STYLESHEETS.values())


@pytest.mark.parametrize("name", sorted(RUNTIME_STYLESHEETS))
def test_registered_stylesheet_is_actually_vendored(name):
    assert (vendor.STYLESHEETS[name].dir / "UPSTREAM").exists()
    assert vendor.recorded_tag(name).startswith("v")


@pytest.mark.parametrize("workflow", ["test.yml", "publish.yml"])
def test_workflow_checks_the_vendored_tree(workflow):
    """Both the pull request and the release path run the same check.

    The release path is the one that matters and the one nothing exercises
    until a release, so it has to be the identical command and not a copy.
    """
    lines = (WORKFLOWS / workflow).read_text().splitlines()
    invocations = [line.strip() for line in lines if "vendor.py" in line]

    assert invocations, f"{workflow} no longer checks the vendored stylesheets"
    for invocation in invocations:
        assert invocation.endswith(vendor.CHECK_COMMAND), (
            f"{workflow} drives vendor.py by hand:\n"
            f"    {invocation}\n\n"
            f"Call `{vendor.CHECK_COMMAND}` instead, which takes the stylesheet "
            f"list and the tags from the script itself, so adding a stylesheet "
            f"does not need a workflow edit."
        )
