"""Are the vendored stylesheets still the latest ones LC has released?

These tests talk to the network, which is usually a thing to keep out of a
default test run. They are in scope here because the vendored stylesheets are
what the package is, and the only way they go red is upstream actually having
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

STYLESHEETS = ["marc2bibframe2", "bibframe2marc"]


def latest_release_tag(repository: str) -> str:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/releases/latest",
        headers={"Accept": "application/vnd.github+json"},
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


@pytest.mark.network
@pytest.mark.parametrize("stylesheet", STYLESHEETS)
def test_vendored_stylesheet_is_the_latest_release(stylesheet):
    vendored = upstream(stylesheet)
    repository = vendored["repository"].removeprefix("https://github.com/")
    latest = latest_release_tag(repository)

    assert vendored["tag"] == latest, (
        f"{stylesheet} {latest} has been released; {vendored['tag']} is "
        f"vendored here.\n"
        f"Re-vendor it with:\n"
        f"\n"
        f"    ./scripts/vendor.py {stylesheet} {latest}\n"
        f"\n"
        f"If a patch in patches/{stylesheet}/ no longer applies, the script "
        f"stops and says which one. That usually means it was fixed upstream "
        f"and can be deleted. Check the diff for behaviour changes before "
        f"releasing:\n"
        f"https://github.com/{repository}/compare/{vendored['tag']}...{latest}"
    )
