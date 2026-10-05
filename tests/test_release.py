"""Unit tests for tools/prepare-release.py — the release math is pure and
must stay pinned: the wrong version here silently ships a wrong package.
S45: version policy. S46: subject parsing. S47: changelog sections."""

import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location(
    "prepare_release",
    os.path.join(os.path.dirname(HERE), "tools", "prepare-release.py"))
pr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pr)


class TestVersionPolicy(unittest.TestCase):
    """S45: the 0.x policy mirrors semantic-release."""

    def c(self, typ, breaking=False):
        return (typ, "scope", breaking, "description", "deadbeef")

    def test_s45_fix_patch(self):
        self.assertEqual(pr.next_version("0.6.2", [self.c("fix")]), "0.6.3")
        # regression: the 0.x fix path once computed 0.0.3 (major reused
        # where minor belonged)
        self.assertNotEqual(pr.next_version("0.6.2", [self.c("fix")]), "0.0.3")

    def test_s45_unknown_type_never_releases(self):
        # legacy subjects shaped like "CI: ..." parse as an unknown type;
        # the kinds filter - not the regex - keeps them from releasing
        self.assertIsNone(pr.next_version("0.6.2", [self.c("CI")]))

    def test_s45_feat_minor(self):
        self.assertEqual(pr.next_version("0.6.2", [self.c("feat")]), "0.7.0")

    def test_s45_breaking_minor_on_0x(self):
        # on the 0.x line breaking stays a minor bump (semver-0x convention)
        self.assertEqual(pr.next_version("0.6.2", [self.c("fix", True)]), "0.7.0")

    def test_s45_breaking_major_from_1x(self):
        self.assertEqual(pr.next_version("1.2.3", [self.c("feat", True)]), "2.0.0")

    def test_s45_feat_minor_from_1x(self):
        self.assertEqual(pr.next_version("1.2.3", [self.c("feat")]), "1.3.0")

    def test_s45_nothing_releasable(self):
        # ci/docs/chore/test/refactor must NEVER trigger a release
        for typ in ("ci", "docs", "chore", "test", "refactor"):
            self.assertIsNone(pr.next_version("0.6.2", [self.c(typ)]), typ)


class TestSubjectParsing(unittest.TestCase):
    """S46: Conventional Commits 1.0.0 subjects."""

    def test_s46_scope_and_bang(self):
        m = pr.SUBJECT.match("feat(plasmoid)!: break things")
        self.assertEqual(m.group("type"), "feat")
        self.assertEqual(m.group("scope"), "plasmoid")
        self.assertEqual(m.group("bang"), "!")
        self.assertEqual(m.group("desc"), "break things")

    def test_s46_plain(self):
        m = pr.SUBJECT.match("fix: a simple fix")
        self.assertEqual(m.group("type"), "fix")
        self.assertIsNone(m.group("scope"))
        self.assertIsNone(m.group("bang"))

    def test_s46_non_conventional_rejected(self):
        # subjects without the type: description shape must not parse
        # ("CI: test suite" IS conventional-shaped: type CI; the kinds
        # filter in next_version is what keeps such types from releasing)
        self.assertIsNone(pr.SUBJECT.match("legacy free-form subject line"))
        self.assertIsNone(pr.SUBJECT.match("release v1.2.3"))


class TestChangelogSection(unittest.TestCase):
    """S47: the generated section groups feat/breaking vs fix."""

    def test_s47_groups(self):
        section = pr.changelog_section("1.2.3", [
            ("fix", None, False, "a fix", "aa1111"),
            ("feat", "plasmoid", False, "a feature", "bb2222"),
        ])
        self.assertIn("## [1.2.3]", section)
        self.assertLess(section.index("### Added"), section.index("### Fixed"))
        self.assertIn("a feature", section)
        self.assertIn("(plasmoid)", section)
        self.assertIn("a fix", section)

    def test_s47_breaking_flagged(self):
        section = pr.changelog_section("1.2.3", [
            ("feat", None, True, "the break", "aa1111"),
        ])
        self.assertIn("(breaking)", section)

    def test_s47_em_dash_header(self):
        # the hand-written sections separate version and date with an
        # em-dash: a generated hyphen header read as a style bug in the
        # 0.7.0/0.7.1 sections
        section = pr.changelog_section("1.2.3", [
            ("fix", None, False, "a fix", "aa1111"),
        ])
        self.assertIn("## [1.2.3] — ", section)
        self.assertNotIn("## [1.2.3] - ", section)


if __name__ == "__main__":
    unittest.main()
