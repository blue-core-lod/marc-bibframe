#!/usr/bin/env python3
"""Re-vendor a Library of Congress conversion stylesheet.

Replaces the vendored copy with a pristine one of the given upstream tag, then
reapplies every patch in patches/<stylesheet>/ in filename order.

    ./scripts/vendor.py marc2bibframe2 v3.1.0
    ./scripts/vendor.py bibframe2marc v3.1.0

With --check it takes no arguments: every stylesheet is re-vendored at the tag
already recorded in its UPSTREAM file and the result compared against what is
committed, which is how CI knows the vendored tree is upstream plus patches and
not a hand-edit.

    ./scripts/vendor.py --check

If a patch no longer applies the script stops and says which one, leaving the
pristine copy in place so the conflict can be resolved by hand. Regenerate the
patch afterwards with:

    git diff -- src/marc_bibframe/<dir>/<file> > patches/<stylesheet>/<name>.patch
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "marc_bibframe"
PATCH_DIR = ROOT / "patches"


@dataclass(frozen=True)
class Stylesheet:
    """An upstream repository and how to lay its files out under the package."""

    repository: str
    #: Directory under src/marc_bibframe/ that the vendored copy lives in.
    target: str
    #: (path in the upstream checkout, path relative to target) pairs to copy.
    copy: tuple[tuple[str, str], ...]
    #: Names to leave behind when copying a directory -- upstream's own test
    #: suites and specs, which we neither run nor ship.
    ignore: tuple[str, ...] = ("test", "tests", "specs")

    @property
    def dir(self) -> Path:
        return PACKAGE / self.target


STYLESHEETS = {
    "marc2bibframe2": Stylesheet(
        repository="https://github.com/lcnetdev/marc2bibframe2",
        target="xsl",
        copy=(("xsl", "."), ("LICENSE", "LICENSE")),
    ),
    # bibframe2marc ships a rules DSL plus the compiler that turns it into the
    # conversion stylesheet, rather than the stylesheet itself. We vendor both
    # and compile at first use -- see marc_bibframe.bibframe_marc. The rules
    # are what patches target, since they are what upstream maintains.
    "bibframe2marc": Stylesheet(
        repository="https://github.com/lcnetdev/bibframe2marc",
        target="bf2marc",
        copy=(
            ("rules", "rules"),
            ("src/compile.xsl", "compile.xsl"),
            ("LICENSE", "LICENSE"),
        ),
    ),
}


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.exit(f"{' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def recorded_tag(name: str) -> str:
    """The upstream tag recorded in a vendored directory's UPSTREAM file."""
    upstream = STYLESHEETS[name].dir / "UPSTREAM"
    if not upstream.exists():
        sys.exit(f"{upstream.relative_to(ROOT)} is missing; nothing is vendored there")
    for line in upstream.read_text().splitlines():
        key, _, value = line.partition(":")
        if key.strip() == "tag":
            return value.strip()
    sys.exit(f"{upstream.relative_to(ROOT)} records no tag")


def vendor(name: str, tag: str) -> None:
    """Replace a vendored copy with upstream at *tag*, then reapply its patches."""
    stylesheet = STYLESHEETS[name]

    with tempfile.TemporaryDirectory() as tmp:
        checkout = Path(tmp) / name
        print(f"fetching {stylesheet.repository} at {tag}")
        run(
            "git",
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--branch",
            tag,
            stylesheet.repository,
            str(checkout),
        )
        commit = run("git", "rev-parse", "HEAD", cwd=checkout)

        shutil.rmtree(stylesheet.dir, ignore_errors=True)
        stylesheet.dir.mkdir(parents=True)
        for source, destination in stylesheet.copy:
            origin = checkout / source
            target = (
                stylesheet.dir if destination == "." else stylesheet.dir / destination
            )
            if origin.is_dir():
                shutil.copytree(
                    origin,
                    target,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*stylesheet.ignore),
                )
            else:
                shutil.copy(origin, target)

    (stylesheet.dir / "UPSTREAM").write_text(
        f"repository: {stylesheet.repository}\ntag: {tag}\ncommit: {commit}\n"
    )
    print(f"vendored {name} {tag} ({commit[:8]})")

    patches = sorted((PATCH_DIR / name).glob("*.patch"))
    if not patches:
        print("no patches to apply")
        return

    for patch in patches:
        check = subprocess.run(
            ["git", "apply", "--check", str(patch)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if check.returncode != 0:
            sys.exit(
                f"\n{patch.name} no longer applies to {name} {tag}:\n"
                f"{check.stderr.strip()}\n\n"
                "It may have been fixed upstream, in which case delete it. "
                "Otherwise reapply it by hand and regenerate the patch."
            )
        run("git", "apply", str(patch), cwd=ROOT)
        print(f"applied {patch.name}")


#: The one command CI runs to check the vendored tree. Both workflows call this
#: rather than spelling out the stylesheet list in shell, so adding a stylesheet
#: to STYLESHEETS above is the only edit needed -- see tests/test_vendor.py,
#: which fails if a workflow goes back to driving this script by hand.
CHECK_COMMAND = "./scripts/vendor.py --check"


def check() -> int:
    """Re-vendor every stylesheet at its recorded tag and report any difference.

    A release ships the vendored stylesheets as the package, so this is what
    stands between a hand-edit of the vendored tree and PyPI.
    """
    targets = [str(s.dir.relative_to(ROOT)) for s in STYLESHEETS.values()]

    # Re-vendoring deletes and rewrites these directories, so uncommitted work
    # in them would vanish -- and be read as "matches upstream" on the way out.
    modified = run("git", "status", "--porcelain", "--", *targets, cwd=ROOT)
    if modified:
        sys.exit(
            "the vendored tree has uncommitted changes, which --check would "
            f"overwrite:\n{modified}\n\n"
            "Commit or stash them first."
        )

    for name in sorted(STYLESHEETS):
        vendor(name, recorded_tag(name))

    changed = run("git", "diff", "--name-only", "--", *targets, cwd=ROOT)
    if changed:
        print(
            f"\nthe vendored tree is not upstream plus patches:\n{changed}\n\n"
            "Either the change belongs in patches/, or it was a hand-edit that "
            "should be dropped with:\n"
            f"\n    git checkout -- {' '.join(targets)}\n",
            file=sys.stderr,
        )
        return 1

    print("\nvendored stylesheets match upstream plus patches")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "stylesheet",
        nargs="?",
        choices=sorted(STYLESHEETS),
        help="which stylesheet to vendor",
    )
    parser.add_argument("tag", nargs="?", help="upstream tag to vendor, e.g. v3.1.0")
    parser.add_argument(
        "--check",
        action="store_true",
        help="re-vendor every stylesheet at the tag recorded in its UPSTREAM "
        "file and exit nonzero if the tree differs; takes no other arguments",
    )
    args = parser.parse_args()

    if args.check:
        if args.stylesheet or args.tag:
            parser.error("--check takes no other arguments")
        sys.exit(check())

    if not args.stylesheet or not args.tag:
        parser.error("both stylesheet and tag are required unless --check is given")

    vendor(args.stylesheet, args.tag)


if __name__ == "__main__":
    main()
