"""
WikiSplice updater — for copies downloaded as a ZIP (no git).

Nothing updates on its own. check() only looks; apply() runs only when the user
says yes (the "Update now" button in the app, or answering "y" here).

    python updater.py        # check, then ask before updating

How it works: GitHub lists every file in the latest version with a fingerprint
(a git "blob" hash). We compute the same fingerprint for the files here; any
that differ or are missing mean an update is available. Updating downloads the
latest ZIP, saves a copy of every file it replaces in .update-backup/<date_time>/,
then installs the new files. It never touches output/, .venv/ or other files
that aren't part of WikiSplice, and never deletes anything.
"""
from __future__ import annotations

import hashlib
import io
import os
import shutil
import sys
import time
import zipfile

REPO = "reedalexschultz/wikisplice"
BRANCH = "main"
HERE = os.path.dirname(os.path.abspath(__file__))
# Never compared or overwritten: your screenshots, Python environment, backups, git data
KEEP = {"output", "wiki_collage", ".venv", ".git", ".update-backup", "__pycache__"}
UA = {"User-Agent": "WikiSplice-updater", "Accept": "application/vnd.github+json"}


def is_git_checkout() -> bool:
    """Cloned with git? Then `git pull` is the right way to update, not this."""
    return os.path.isdir(os.path.join(HERE, ".git"))


def _blob_sha(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _managed(path: str) -> bool:
    return path.split("/")[0] not in KEEP


def _changed_files(tree: list) -> list[str]:
    changed = []
    for entry in tree:
        if entry.get("type") != "blob" or not _managed(entry["path"]):
            continue
        local = os.path.join(HERE, *entry["path"].split("/"))
        if not os.path.isfile(local) or _blob_sha(local) != entry["sha"]:
            changed.append(entry["path"])
    return changed


def check(timeout: float = 15) -> dict:
    """Look for a newer version. Read-only: downloads a file list, changes nothing."""
    import requests
    if is_git_checkout():
        return {"available": False, "git": True}
    tree = requests.get(f"https://api.github.com/repos/{REPO}/git/trees/{BRANCH}?recursive=1",
                        headers=UA, timeout=timeout)
    tree.raise_for_status()
    changed = _changed_files(tree.json().get("tree", []))
    latest = {}
    if changed:
        try:
            c = requests.get(f"https://api.github.com/repos/{REPO}/commits/{BRANCH}", headers=UA, timeout=timeout)
            c.raise_for_status()
            info = c.json()
            latest = {
                "sha": info["sha"][:7],
                "message": info["commit"]["message"].split("\n")[0],
                "date": info["commit"]["committer"]["date"][:10],
            }
        except Exception:
            pass  # the file list is what matters; the description is just nice to have
    return {"available": bool(changed), "git": False, "changed": changed, "latest": latest,
            "version": tree.json().get("sha", "")[:12]}


def apply(timeout: float = 60) -> dict:
    """Download and install the latest version. Only call this after the user agreed."""
    import requests
    if is_git_checkout():
        raise RuntimeError("This copy was cloned with git. Update it with `git pull` instead.")

    r = requests.get(f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}", headers=UA, timeout=timeout)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))

    backup_dir = os.path.join(HERE, ".update-backup", time.strftime("%Y-%m-%d_%H-%M-%S"))
    updated: list[str] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        # GitHub ZIPs put everything in one top folder, e.g. "wikisplice-main/app.py"
        parts = info.filename.split("/", 1)
        if len(parts) < 2 or not parts[1]:
            continue
        rel = parts[1]
        if not _managed(rel) or ".." in rel.split("/") or rel.startswith("/"):
            continue
        dest = os.path.join(HERE, *rel.split("/"))
        if not os.path.realpath(dest).startswith(os.path.realpath(HERE) + os.sep):
            continue  # refuse anything that would land outside this folder
        data = zf.read(info)
        if os.path.isfile(dest):
            with open(dest, "rb") as f:
                if f.read() == data:
                    continue  # already up to date
            os.makedirs(os.path.dirname(os.path.join(backup_dir, rel)), exist_ok=True)
            shutil.copy2(dest, os.path.join(backup_dir, rel))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".updating"
        with open(tmp, "wb") as f:
            f.write(data)
        mode = (info.external_attr >> 16) & 0o777
        os.chmod(tmp, mode or 0o644)  # keeps "Start WikiSplice.command" double-clickable
        os.replace(tmp, dest)
        updated.append(rel)

    return {"updated": updated, "backup": backup_dir if os.path.isdir(backup_dir) else "",
            "requirements_changed": "requirements.txt" in updated}


def main() -> None:
    if is_git_checkout():
        print("This copy was cloned with git. Update it with:  git pull")
        return
    print("Checking GitHub for a newer version of WikiSplice...")
    try:
        result = check()
    except Exception as e:
        sys.exit(f"Couldn't check for updates: {e}")
    if not result["available"]:
        print("You're up to date.")
        return
    latest = result.get("latest") or {}
    print(f"\nA new version is available: {len(result['changed'])} file(s) changed.")
    if latest:
        print(f"Latest change ({latest['date']}): {latest['message']}")
    print("Your output/ folder and settings won't be touched, and replaced files are backed up.")
    if input("\nUpdate now? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Not updated.")
        return
    done = apply()
    print(f"Updated {len(done['updated'])} file(s).")
    if done["backup"]:
        print(f"Previous versions saved in {done['backup']}")
    print("Restart WikiSplice to use the new version.")


if __name__ == "__main__":
    main()
