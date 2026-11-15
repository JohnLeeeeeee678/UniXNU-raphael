"""Push the local commits to GitHub through the REST API.

The git transport keeps dying with an SSL EOF on this machine, so the
tree is uploaded with the git data API instead: blob -> tree -> commit ->
ref update.
"""

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = "JohnLeeeeeee678/UniXNU-raphael"
BRANCH = "main"
TOKEN = open("D:/raphael-ios/work/_tok.txt").read().strip()
LOCAL = "C:/Users/JohnTech/WorkBuddy/2026-10-25-16-03-19/raphael-port/UniXNU-raphael"


def api(url, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "User-Agent": "workbuddy",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:400]
            if e.code in (502, 503, 504) and attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            raise SystemExit("HTTP %d %s\n%s" % (e.code, url, body))
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(3 * (attempt + 1))
                continue
            raise SystemExit("URL error %s" % e)
    raise SystemExit("unreachable")


def git(*args):
    return subprocess.run(
        ["git", "-C", LOCAL] + list(args),
        capture_output=True, text=True, check=True).stdout


def remote_tree(repo, sha):
    """Return {path: blob sha} for a commit."""
    out = {}
    stack = [{"sha": sha, "prefix": ""}]
    while stack:
        node = stack.pop()
        j = api("https://api.github.com/repos/%s/git/trees/%s"
                % (repo, node["sha"]))
        for entry in j.get("tree", []):
            path = node["prefix"] + entry["path"]
            if entry["type"] == "tree":
                stack.append({"sha": entry["sha"], "prefix": path + "/"})
            else:
                out[path] = entry["sha"]
        if j.get("truncated"):
            raise SystemExit("the tree is truncated, cannot compare")
    return out


def main():
    refs = api("https://api.github.com/repos/%s/git/refs/heads" % REPO)
    remote_sha = None
    for r in refs:
        if r["ref"] == "refs/heads/" + BRANCH:
            remote_sha = r["object"]["sha"]
    if not remote_sha:
        raise SystemExit("branch %s not found" % BRANCH)
    print("remote %s = %s" % (BRANCH, remote_sha))

    base = api("https://api.github.com/repos/%s/git/commits/%s"
               % (REPO, remote_sha))
    remote_files = remote_tree(REPO, base["tree"]["sha"])

    local_files = git("ls-tree", "-r", "--name-only", "HEAD").split()
    files = []
    for path in local_files:
        content = subprocess.run(
            ["git", "-C", LOCAL, "show", "HEAD:" + path],
            capture_output=True, check=True).stdout
        blob = api("https://api.github.com/repos/%s/git/blobs" % REPO,
                   {"content": base64.b64encode(content).decode(),
                    "encoding": "base64"})
        if remote_files.get(path) != blob["sha"]:
            files.append((path, blob["sha"]))

    print("files to push: %d of %d" % (len(files), len(local_files)))
    if not files:
        print("nothing to push")
        return

    tree_entries = []
    for path, sha in files:
        tree_entries.append({"path": path, "mode": "100644", "type": "blob",
                             "sha": sha})
        print("  blob %s %s" % (sha[:8], path))

    tree = api(
        "https://api.github.com/repos/%s/git/trees" % REPO,
        {"base_tree": base["tree"]["sha"], "tree": tree_entries})
    print("tree:", tree["sha"])

    commit = api(
        "https://api.github.com/repos/%s/git/commits" % REPO,
        {"message": "Bring the port up to date\n\n"
                    "Adds the kernel binary patcher with the control transfer\n"
                    "status direction fix, the touch offset alignment fix, the\n"
                    "SM8150 touch clock fix and the tools that verify them.\n",
         "tree": tree["sha"], "parents": [remote_sha]})
    print("commit:", commit["sha"])

    api("https://api.github.com/repos/%s/git/refs/heads/%s"
        % (REPO, BRANCH),
        {"sha": commit["sha"], "force": False}, method="PATCH")
    print("ref updated ->", commit["sha"])


if __name__ == "__main__":
    main()
