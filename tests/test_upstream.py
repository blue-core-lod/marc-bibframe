"""Is the vendored stylesheet still the latest one LC has released?

This one test talks to the network, which is usually a thing to keep out of a
default test run. It is in scope here because the vendored stylesheets are
what the package is, and the only way it goes red is upstream actually having
released something -- an unreachable API or a spent rate limit skips.

The cost is that an upstream release turns unrelated pull requests red until
someone re-vendors. That is the intended nag.
"""

import json
import os
import urllib.error
import urllib.request

import pytest

from marc_bibframe import upstream

LATEST = "https://api.github.com/repos/lcnetdev/marc2bibframe2/releases/latest"


def latest_release_tag() -> str:
    request = urllib.request.Request(
        LATEST, headers={"Accept": "application/vnd.github+json"}
    )
    # Authenticated when a token is around: the anonymous rate limit is 60 an
    # hour per IP address, which shared CI runners burn through.
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)["tag_name"]
    except (urllib.error.URLError, TimeoutError) as error:
        # HTTPError subclasses URLError, so a spent rate limit lands here too.
        pytest.skip(f"could not reach the GitHub API: {error}")


def test_vendored_stylesheet_is_the_latest_release():
    vendored = upstream()["tag"]
    latest = latest_release_tag()

    assert vendored == latest, (
        f"marc2bibframe2 {latest} has been released; {vendored} is vendored here.\n"
        f"Re-vendor it with:\n"
        f"\n"
        f"    ./scripts/vendor.py {latest}\n"
        f"\n"
        f"If a patch in patches/ no longer applies, the script stops and says "
        f"which one. That usually means it was fixed upstream and can be "
        f"deleted. Check the diff for behaviour changes before releasing:\n"
        f"https://github.com/lcnetdev/marc2bibframe2/compare/{vendored}...{latest}"
    )
