#!/usr/bin/env python3
"""Re-vendor the Library of Congress marc2bibframe2 stylesheets.

Replaces src/marc_bibframe/xsl with a pristine copy of the given upstream tag,
then reapplies every patch in patches/ in filename order.

    ./scripts/vendor.py v3.1.0

If a patch no longer applies the script stops and says which one, leaving the
pristine copy in place so the conflict can be resolved by hand. Regenerate the
patch afterwards with:

    git diff -- src/marc_bibframe/xsl/<file> > patches/<name>.patch
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

UPSTREAM = "https://github.com/lcnetdev/marc2bibframe2"

ROOT = Path(__file__).resolve().parent.parent
XSL_DIR = ROOT / "src" / "marc_bibframe" / "xsl"
PATCH_DIR = ROOT / "patches"


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.exit(f"{' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="upstream tag to vendor, e.g. v3.1.0")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        checkout = Path(tmp) / "marc2bibframe2"
        print(f"fetching {UPSTREAM} at {args.tag}")
        run(
            "git",
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--branch",
            args.tag,
            UPSTREAM,
            str(checkout),
        )
        commit = run("git", "rev-parse", "HEAD", cwd=checkout)

        shutil.rmtree(XSL_DIR)
        shutil.copytree(checkout / "xsl", XSL_DIR)
        shutil.copy(checkout / "LICENSE", XSL_DIR / "LICENSE")

    (XSL_DIR / "UPSTREAM").write_text(
        f"repository: {UPSTREAM}\ntag: {args.tag}\ncommit: {commit}\n"
    )
    print(f"vendored {args.tag} ({commit[:8]})")

    patches = sorted(PATCH_DIR.glob("*.patch"))
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
                f"\n{patch.name} no longer applies to {args.tag}:\n"
                f"{check.stderr.strip()}\n\n"
                "It may have been fixed upstream, in which case delete it. "
                "Otherwise reapply it by hand and regenerate the patch."
            )
        run("git", "apply", str(patch), cwd=ROOT)
        print(f"applied {patch.name}")


if __name__ == "__main__":
    main()
