#!/usr/bin/env python3
"""Re-vendor a Library of Congress conversion stylesheet.

Replaces the vendored copy with a pristine one of the given upstream tag, then
reapplies every patch in patches/<stylesheet>/ in filename order.

    ./scripts/vendor.py marc2bibframe2 v3.1.0
    ./scripts/vendor.py bibframe2marc v3.1.0

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "stylesheet", choices=sorted(STYLESHEETS), help="which stylesheet to vendor"
    )
    parser.add_argument("tag", help="upstream tag to vendor, e.g. v3.1.0")
    args = parser.parse_args()

    stylesheet = STYLESHEETS[args.stylesheet]

    with tempfile.TemporaryDirectory() as tmp:
        checkout = Path(tmp) / args.stylesheet
        print(f"fetching {stylesheet.repository} at {args.tag}")
        run(
            "git",
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--branch",
            args.tag,
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
        f"repository: {stylesheet.repository}\ntag: {args.tag}\ncommit: {commit}\n"
    )
    print(f"vendored {args.stylesheet} {args.tag} ({commit[:8]})")

    patches = sorted((PATCH_DIR / args.stylesheet).glob("*.patch"))
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
                f"\n{patch.name} no longer applies to {args.stylesheet} {args.tag}:\n"
                f"{check.stderr.strip()}\n\n"
                "It may have been fixed upstream, in which case delete it. "
                "Otherwise reapply it by hand and regenerate the patch."
            )
        run("git", "apply", str(patch), cwd=ROOT)
        print(f"applied {patch.name}")


if __name__ == "__main__":
    main()
