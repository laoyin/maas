# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test version utilities."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []

import random

from bzrlib.errors import NotBranchError
from maasserver.utils import version
from maastesting.matchers import MockCalledOnceWith
from maastesting.testcase import MAASTestCase
from mock import (
    MagicMock,
    sentinel,
)
from testtools.matchers import Is


class TestGetVersionFromAPT(MAASTestCase):

    def test__creates_cache_with_None_progress(self):
        mock_Cache = self.patch(version.apt_pkg, "Cache")
        version.get_version_from_apt(version.REGION_PACKAGE_NAME)
        self.assertThat(mock_Cache, MockCalledOnceWith(None))

    def test__returns_empty_string_if_package_not_in_cache(self):
        self.patch(version.apt_pkg, "Cache")
        self.assertEquals(
            "",
            version.get_version_from_apt(version.REGION_PACKAGE_NAME))

    def test__returns_empty_string_if_not_current_ver_from_package(self):
        package = MagicMock()
        package.current_ver = None
        mock_cache = {
            version.REGION_PACKAGE_NAME: package,
            }
        self.patch(version.apt_pkg, "Cache").return_value = mock_cache
        self.assertEquals(
            "",
            version.get_version_from_apt(version.REGION_PACKAGE_NAME))

    def test__returns_ver_str_from_package(self):
        package = MagicMock()
        package.current_ver.ver_str = sentinel.ver_str
        mock_cache = {
            version.REGION_PACKAGE_NAME: package,
            }
        self.patch(version.apt_pkg, "Cache").return_value = mock_cache
        self.assertIs(
            sentinel.ver_str,
            version.get_version_from_apt(version.REGION_PACKAGE_NAME))


class TestGetMAASBranch(MAASTestCase):

    def test__returns_None_if_Branch_is_None(self):
        self.patch(version, "Branch", None)
        self.assertIsNone(version.get_maas_branch())

    def test__calls_Branch_open_with_current_dir(self):
        mock_open = self.patch(version.Branch, "open")
        mock_open.return_value = sentinel.branch
        self.expectThat(version.get_maas_branch(), Is(sentinel.branch))
        self.expectThat(mock_open, MockCalledOnceWith("."))

    def test__returns_None_on_NotBranchError(self):
        mock_open = self.patch(version.Branch, "open")
        mock_open.side_effect = NotBranchError("")
        self.assertIsNone(version.get_maas_branch())


class TestExtractVersionSubversion(MAASTestCase):

    scenarios = [
        ("with ~", {
            "version": "1.8.0~alpha4+bzr356-0ubuntu1",
            "output": ("1.8.0", "alpha4+bzr356"),
            }),
        ("without ~", {
            "version": "1.8.0+bzr356-0ubuntu1",
            "output": ("1.8.0", "+bzr356"),
            }),
        ("without ~ or +", {
            "version": "1.8.0-0ubuntu1",
            "output": ("1.8.0", ""),
            }),
    ]

    def test__returns_version_subversion(self):
        self.assertEquals(
            self.output, version.extract_version_subversion(self.version))


class TestVersionTestCase(MAASTestCase):
    """MAASTestCase that resets the cache used by utility methods."""

    def setUp(self):
        super(TestVersionTestCase, self).setUp()
        self.patch(version, "_cache", {})


class TestGetMAASPackageVersion(TestVersionTestCase):

    def test__calls_get_version_from_apt(self):
        mock_apt = self.patch(version, "get_version_from_apt")
        mock_apt.return_value = sentinel.version
        self.expectThat(
            version.get_maas_package_version(), Is(sentinel.version))
        self.expectThat(
            mock_apt, MockCalledOnceWith(version.REGION_PACKAGE_NAME))


class TestGetMAASVersionSubversion(TestVersionTestCase):

    def test__returns_package_version(self):
        mock_apt = self.patch(version, "get_version_from_apt")
        mock_apt.return_value = "1.8.0~alpha4+bzr356-0ubuntu1"
        self.assertEquals(
            ("1.8.0", "alpha4+bzr356"), version.get_maas_version_subversion())

    def test__returns_unknown_if_version_is_empty_and_not_bzr_branch(self):
        mock_version = self.patch(version, "get_version_from_apt")
        mock_version.return_value = ""
        mock_branch = self.patch(version, "get_maas_branch")
        mock_branch.return_value = None
        self.assertEquals(
            ("unknown", ""), version.get_maas_version_subversion())

    def test__returns_from_source_and_revno_from_branch(self):
        mock_version = self.patch(version, "get_version_from_apt")
        mock_version.return_value = ""
        revno = random.randint(1, 5000)
        mock_branch = self.patch(version, "get_maas_branch")
        mock_branch.return_value.revno.return_value = revno
        self.assertEquals(
            ("from source (+bzr%s)" % revno, ""),
            version.get_maas_version_subversion())


class TestGetMAASVersionUI(TestVersionTestCase):

    def test__returns_package_version(self):
        mock_apt = self.patch(version, "get_version_from_apt")
        mock_apt.return_value = "1.8.0~alpha4+bzr356-0ubuntu1"
        self.assertEquals(
            "1.8.0 (alpha4+bzr356)", version.get_maas_version_ui())

    def test__returns_unknown_if_version_is_empty_and_not_bzr_branch(self):
        mock_version = self.patch(version, "get_version_from_apt")
        mock_version.return_value = ""
        mock_branch = self.patch(version, "get_maas_branch")
        mock_branch.return_value = None
        self.assertEquals("unknown", version.get_maas_version_ui())

    def test__returns_from_source_and_revno_from_branch(self):
        mock_version = self.patch(version, "get_version_from_apt")
        mock_version.return_value = ""
        revno = random.randint(1, 5000)
        mock_branch = self.patch(version, "get_maas_branch")
        mock_branch.return_value.revno.return_value = revno
        self.assertEquals(
            "from source (+bzr%s)" % revno, version.get_maas_version_ui())


class TestGetMAASDocVersion(TestVersionTestCase):

    def test__returns_doc_version_with_greater_than_1_decimals(self):
        mock_apt = self.patch(version, "get_version_from_apt")
        mock_apt.return_value = "1.8.0~alpha4+bzr356-0ubuntu1"
        self.assertEquals("docs1.8", version.get_maas_doc_version())

    def test__returns_doc_version_with_equal_to_1_decimals(self):
        mock_apt = self.patch(version, "get_version_from_apt")
        mock_apt.return_value = "1.8~alpha4+bzr356-0ubuntu1"
        self.assertEquals("docs1.8", version.get_maas_doc_version())

    def test__returns_just_doc_if_version_is_empty(self):
        mock_apt = self.patch(version, "get_version_from_apt")
        mock_apt.return_value = ""
        self.assertEquals("docs", version.get_maas_doc_version())


class TestVersionMethodsCached(TestVersionTestCase):

    scenarios = [
        ("get_maas_package_version", dict(method="get_maas_package_version")),
        ("get_maas_version_subversion", dict(
            method="get_maas_version_subversion")),
        ("get_maas_version_ui", dict(method="get_maas_version_ui")),
        ("get_maas_doc_version", dict(method="get_maas_doc_version")),
        ]

    def test_method_is_cached(self):
        mock_apt = self.patch(version, "get_version_from_apt")
        mock_apt.return_value = "1.8.0~alpha4+bzr356-0ubuntu1"
        cached_method = getattr(version, self.method)
        first_return_value = cached_method()
        second_return_value = cached_method()
        # The return value is not empty (full unit tests have been performed
        # earlier).
        self.assertNotIn(first_return_value, [b'', u'', None])
        self.assertEqual(first_return_value, second_return_value)
        # Apt has only been called once.
        self.expectThat(
            mock_apt, MockCalledOnceWith(version.REGION_PACKAGE_NAME))