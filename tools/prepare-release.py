#!/usr/bin/env python3
"""Prepare the next cooling-ctl release from the conventional commits made
since the last version tag.

Usage:
  prepare-release.py --check   print the next version, or "none" when the
                               commits since the tag cannot release
  prepare-release.py            apply: insert the CHANGELOG.md section,
                               bump metadata.json Version and PKGBUILD
                               (pkgver, pkgrel reset to 1), print the
                               release notes markdown on stdout

Everything else - branch, commit, PR, tag, package build - is the release
workflow's job (.github/workflows/release.yml). Version policy mirrors
semantic-release on the 0.x line: fix -> patch, feat -> minor, breaking
change (any type with "!" or a BREAKING CHANGE footer) -> minor while the
major stays 0. Fails loudly, never guesses.
"""

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METADATA = ROOT / "plasmoid" / "org.coolingctl" / "metadata.json"
PKGBUILD = ROOT / "PKGBUILD"
CHANGELOG = ROOT / "CHANGELOG.md"

# subject regex: type(scope)!: description (Conventional Commits 1.0.0)
SUBJECT = re.compile(r"^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?: (?P<desc>.+)$")


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          check=True, capture_output=True, text=True).stdout


def last_version():
    """The newest vX.Y.Z tag, or 0.0.0 when none exists yet."""
    tags = git("tag", "-l", "v[0-9]*", "--sort=-v:refname").splitlines()
    return tags[0][1:] if tags else "0.0.0"


# log record: sha NUL subject NUL body NUL (%x00 separators cannot collide
# with content the way @-based ones did - lived bug: runs of empty-body
# records shifted every field by one and all feat/fix commits vanished)
def commits_since(tag_version):
    """[(type, scope, breaking, description, sha)] since the tag."""
    out = git("log", "v" + tag_version + "..HEAD", "--no-merges",
              "--pretty=format:%h%x00%s%x00%b%x00")
    fields = out.split("\x00")
    commits = []
    for i in range(0, len(fields) - 2, 3):
        sha, subject, body = fields[i].strip("\n"), fields[i + 1].strip(), fields[i + 2]
        sm = SUBJECT.match(subject)
        if not sm:
            continue          # not conventional (e.g. legacy subjects): ignored
        breaking = bool(sm.group("bang")) or "BREAKING CHANGE:" in body.upper()
        commits.append((sm.group("type"), sm.group("scope"), breaking,
                        sm.group("desc"), sha))
    return commits


def next_version(cur, commits):
    """Release policy; None when no commit can release."""
    major, minor, patch = (int(x) for x in cur.split("."))
    kinds = set()
    for typ, _scope, breaking, _desc, _sha in commits:
        if breaking:
            kinds.add("breaking")
        elif typ == "feat":
            kinds.add("feat")
        elif typ == "fix":
            kinds.add("fix")
    if not kinds:
        return None
    if major == 0:
        # 0.x: breaking and feat both bump the minor line
        if kinds & {"breaking", "feat"}:
            return "0." + str(minor + 1) + ".0"
        return "0." + str(minor) + "." + str(patch + 1)
    if "breaking" in kinds:
        return str(major + 1) + ".0.0"
    if "feat" in kinds:
        return str(major) + "." + str(minor + 1) + ".0"
    return str(major) + "." + str(minor) + "." + str(patch + 1)


def changelog_section(version, commits):
    """Keep-a-Changelog-flavoured section for the release."""
    lines = ["## [" + version + "] - " + date.today().isoformat(), ""]
    feats = [c for c in commits if c[0] == "feat" or c[2]]
    fixes = [c for c in commits if c[0] == "fix" and not c[2]]
    if feats:
        lines.append("### Added")
        for typ, scope, breaking, desc, sha in feats:
            scope_s = "(" + scope + ")" if scope else ""
            bang = " (breaking)" if breaking else ""
            lines.append("- " + desc + bang + " - `" + typ + scope_s + "` (" + sha + ")")
        lines.append("")
    if fixes:
        lines.append("### Fixed")
        for typ, scope, breaking, desc, sha in fixes:
            scope_s = "(" + scope + ")" if scope else ""
            lines.append("- " + desc + " - `fix" + scope_s + "` (" + sha + ")")
        lines.append("")
    return "\n".join(lines)


def notes_markdown(version, commits):
    lines = ["Release **v" + version + "**", ""]
    for typ, scope, breaking, desc, sha in commits:
        scope_s = "(" + scope + ")" if scope else ""
        bang = " **BREAKING**" if breaking else ""
        lines.append("- `" + typ + scope_s + ":`" + bang + " " + desc + " (" + sha + ")")
    return "\n".join(lines)


def apply_release(version, commits):
    """Mutate CHANGELOG.md, metadata.json and PKGBUILD; return the notes."""
    # changelog: insert before the first existing release header
    log = CHANGELOG.read_text()
    anchor = re.search(r"^## \[", log, re.M)
    if not anchor:
        sys.exit("cannot find a release header in CHANGELOG.md")
    log = log[:anchor.start()] + changelog_section(version, commits) + "\n" + log[anchor.start():]
    CHANGELOG.write_text(log)

    # metadata.json: the single "Version" field
    meta = METADATA.read_text()
    meta, n = re.subn(r'"Version": "[0-9.]+"', '"Version": "' + version + '"', meta, count=1)
    if n != 1:
        sys.exit("cannot bump metadata.json Version")
    METADATA.write_text(meta)

    # PKGBUILD: pkgver + pkgrel reset
    pkg = PKGBUILD.read_text()
    pkg, n1 = re.subn(r"^pkgver=[0-9.]+$", "pkgver=" + version, pkg, count=1, flags=re.M)
    pkg, n2 = re.subn(r"^pkgrel=\d+$", "pkgrel=1", pkg, count=1, flags=re.M)
    if n1 != 1 or n2 != 1:
        sys.exit("cannot bump PKGBUILD pkgver/pkgrel")
    PKGBUILD.write_text(pkg)

    return notes_markdown(version, commits)


def main():
    cur = last_version()
    commits = commits_since(cur)
    version = next_version(cur, commits)
    if "--check" in sys.argv:
        print(version if version else "none")
        return
    if not version:
        sys.exit("nothing to release: no feat/fix/breaking commit since v" + cur)
    notes = apply_release(version, commits)
    print(notes)


if __name__ == "__main__":
    main()
