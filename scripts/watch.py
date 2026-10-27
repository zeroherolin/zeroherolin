#!/usr/bin/env python3
"""Dispatch the render workflow when the account's public repositories change.

GitHub has no event for a repository being created or deleted on a personal
account, so .github/workflows/watch.yml runs this every few minutes. render.py
ends README.md with a comment recording the repositories it was generated from;
when the account's list now differs (a repository was created, forked, deleted,
renamed or made public or private, or a new repository's language was detected)
render.yml is dispatched, instead of waiting for its daily run.

  python3 scripts/watch.py            check, and dispatch on a change
  python3 scripts/watch.py --dry-run  only report what would happen

Failing to read from GitHub (an outage, a rate limit) only warns: the next
check tries again. Uses only the standard library and the gh CLI; GITHUB_TOKEN
is optional.
"""

import base64
import os
import re
import subprocess
import sys
import urllib.error
from datetime import datetime, timedelta, timezone

import render

REPO = os.environ.get("GITHUB_REPOSITORY", f"{render.USER}/{render.USER}")
API = f"https://api.github.com/repos/{REPO}"
WORKFLOW = "render.yml"
RECORD = re.compile(r"<!-- repos: (.*?) -->", re.S)
RETRY_AFTER_FAILURE = timedelta(hours=3)  # a render that keeps failing is not dispatched over and over


def recorded():
    """The repositories README.md says it was generated from; none if it says nothing."""
    try:
        file = render.get(f"{API}/contents/README.md")
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return set()
        raise
    try:
        text = base64.b64decode(file["content"]).decode()
    except (KeyError, TypeError, ValueError):  # not a file, or garbled
        return set()
    found = RECORD.search(text)
    return set(found.group(1).split()) if found else set()


def latest_render():
    runs = render.get(f"{API}/actions/workflows/{WORKFLOW}/runs?per_page=1")["workflow_runs"]
    return runs[0] if runs else None


def check():
    """(changes, latest render run) if the account differs from README.md's record, else None."""
    current = set(render.repo_state(render.owned_repos()))
    seen = recorded()
    added, removed = sorted(current - seen), sorted(seen - current)
    if not added and not removed:
        print(f"Repository list unchanged ({len(current)} public repositories)")
        return None
    return [f"+ {t}" for t in added] + [f"- {t}" for t in removed], latest_render()


def report(changes, outcome):
    """Print what changed and what was done; on GitHub Actions, put it on the run's summary page too."""
    print("\n".join([*changes, "", outcome]))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Repository list changed\n\n" + "\n".join(f"- `{c}`" for c in changes) + f"\n\n{outcome}\n")


def main(dry_run):
    try:
        found = check()
    except render.NETWORK_ERRORS as err:
        if not render.transient(err):  # bad credentials, a missing repository: say so loudly
            raise
        render.warn(f"could not read from GitHub ({err!r}); trying again at the next check")
        return
    if found is None:
        return
    changes, run = found

    if run and run["status"] != "completed":
        report(changes, "A render is already running; the next check sees whether it recorded these changes.")
        return
    if run and run["conclusion"] in ("failure", "timed_out"):
        age = datetime.now(timezone.utc) - datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
        if age < RETRY_AFTER_FAILURE:
            render.warn(f"the last {WORKFLOW} run failed {int(age.total_seconds() // 60)} minutes ago; "
                        "not dispatching another until it is fixed or 3 hours have passed")
            report(changes, "Not dispatched: the last render failed.")
            return
    if dry_run:
        report(changes, f"Dry run: would dispatch {WORKFLOW}.")
        return
    subprocess.run(["gh", "workflow", "run", WORKFLOW, "--repo", REPO], check=True)
    report(changes, f"Dispatched {WORKFLOW}.")


if __name__ == "__main__":
    main("--dry-run" in sys.argv[1:])
