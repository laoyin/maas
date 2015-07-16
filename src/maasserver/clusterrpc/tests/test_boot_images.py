# Copyright 2014-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the `boot_images` module."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []

import os

from maasserver.clusterrpc.boot_images import (
    get_all_available_boot_images,
    get_boot_images,
    get_boot_images_for,
    get_common_available_boot_images,
    is_import_boot_images_running,
    is_import_boot_images_running_for,
)
from maasserver.clusterrpc.testing.boot_images import make_rpc_boot_image
from maasserver.enum import (
    BOOT_RESOURCE_TYPE,
    NODEGROUP_STATUS,
)
from maasserver.rpc import getAllClients
from maasserver.rpc.testing.fixtures import RunningClusterRPCFixture
from maasserver.testing.factory import factory
from maasserver.testing.testcase import MAASServerTestCase
from provisioningserver.boot.tests import test_tftppath
from provisioningserver.boot.tftppath import (
    compose_image_path,
    locate_tftp_path,
)
from provisioningserver.rpc import (
    boot_images,
    clusterservice,
)
from provisioningserver.testing.boot_images import (
    make_boot_image_storage_params,
    make_image,
)
from provisioningserver.testing.config import ClusterConfigurationFixture
from twisted.internet.defer import succeed


def make_image_dir(image_params, tftp_root):
    """Fake a boot image matching `image_params` under `tftp_root`."""
    image_dir = locate_tftp_path(
        compose_image_path(
            osystem=image_params['osystem'],
            arch=image_params['architecture'],
            subarch=image_params['subarchitecture'],
            release=image_params['release'],
            label=image_params['label']),
        tftp_root)
    os.makedirs(image_dir)
    factory.make_file(image_dir, 'linux')
    factory.make_file(image_dir, 'initrd.gz')


class TestIsImportBootImagesRunning(MAASServerTestCase):
    """Tests for `is_import_boot_images_running`."""

    def test_returns_True_when_one_cluster_returns_True(self):
        factory.make_NodeGroup().accept()
        factory.make_NodeGroup().accept()
        factory.make_NodeGroup().accept()
        self.useFixture(RunningClusterRPCFixture())

        clients = getAllClients()
        for index, client in enumerate(clients):
            callRemote = self.patch(client._conn, "callRemote")
            if index == 0:
                # The first client returns all False.
                callRemote.return_value = succeed({'running': False})
            else:
                # All clients but the first return True.
                callRemote.return_value = succeed({'running': True})

        self.assertTrue(is_import_boot_images_running())

    def test_returns_False_when_all_clusters_return_False(self):
        factory.make_NodeGroup().accept()
        factory.make_NodeGroup().accept()
        factory.make_NodeGroup().accept()
        self.useFixture(RunningClusterRPCFixture())

        clients = getAllClients()
        for index, client in enumerate(clients):
            callRemote = self.patch(client._conn, "callRemote")
            callRemote.return_value = succeed({'running': False})

        self.assertFalse(is_import_boot_images_running())

    def test_ignores_failures_when_talking_to_clusters(self):
        factory.make_NodeGroup().accept()
        factory.make_NodeGroup().accept()
        factory.make_NodeGroup().accept()
        self.useFixture(RunningClusterRPCFixture())

        clients = getAllClients()
        for index, client in enumerate(clients):
            callRemote = self.patch(client._conn, "callRemote")
            if index == 0:
                # The first client returns True.
                callRemote.return_value = succeed({'running': True})
            else:
                # All clients but the first raise an exception.
                callRemote.side_effect = ZeroDivisionError()

        self.assertTrue(is_import_boot_images_running())


class TestIsImportBootImagesRunningFor(MAASServerTestCase):
    """Tests for `is_import_boot_images_running_for`."""

    def test_returns_True(self):
        mock_is_running = self.patch(
            clusterservice, "is_import_boot_images_running")
        mock_is_running.return_value = True
        nodegroup = factory.make_NodeGroup(status=NODEGROUP_STATUS.ENABLED)
        self.useFixture(RunningClusterRPCFixture())
        self.assertTrue(is_import_boot_images_running_for(nodegroup))

    def test_returns_False(self):
        mock_is_running = self.patch(
            clusterservice, "is_import_boot_images_running")
        mock_is_running.return_value = False
        nodegroup = factory.make_NodeGroup(status=NODEGROUP_STATUS.ENABLED)
        self.useFixture(RunningClusterRPCFixture())
        self.assertFalse(is_import_boot_images_running_for(nodegroup))


def prepare_tftp_root(test):
    """Create a `current` directory and configure its use."""
    test.tftp_root = os.path.join(test.make_dir(), 'current')
    os.mkdir(test.tftp_root)
    test.patch(boot_images, 'CACHED_BOOT_IMAGES', None)
    config = ClusterConfigurationFixture(tftp_root=test.tftp_root)
    test.useFixture(config)


class TestGetBootImages(MAASServerTestCase):
    """Tests for `get_boot_images`."""

    def setUp(self):
        super(TestGetBootImages, self).setUp()
        prepare_tftp_root(self)  # Sets self.tftp_root.

    def test_returns_boot_images(self):
        nodegroup = factory.make_NodeGroup(status=NODEGROUP_STATUS.ENABLED)
        self.useFixture(RunningClusterRPCFixture())

        purposes = ['install', 'commissioning', 'xinstall']
        params = [make_boot_image_storage_params() for _ in range(3)]
        for param in params:
            make_image_dir(param, self.tftp_root)
            test_tftppath.make_osystem(self, param['osystem'], purposes)
        self.assertItemsEqual(
            [
                make_image(param, purpose)
                for param in params
                for purpose in purposes
            ],
            get_boot_images(nodegroup))


class TestGetAvailableBootImages(MAASServerTestCase):
    """Tests for `get_common_available_boot_images` and
    `get_all_available_boot_images`."""

    scenarios = (
        ("get_common_available_boot_images", {
            "get": get_common_available_boot_images,
            "all": False,
        }),
        ("get_all_available_boot_images", {
            "get": get_all_available_boot_images,
            "all": True,
        }),
    )

    def setUp(self):
        super(TestGetAvailableBootImages, self).setUp()
        prepare_tftp_root(self)  # Sets self.tftp_root.

    def test_returns_boot_images_for_one_cluster(self):
        factory.make_NodeGroup().accept()
        self.useFixture(RunningClusterRPCFixture())

        purposes = ['install', 'commissioning', 'xinstall']
        params = [make_boot_image_storage_params() for _ in range(3)]
        for param in params:
            make_image_dir(param, self.tftp_root)
            test_tftppath.make_osystem(self, param['osystem'], purposes)
        self.assertItemsEqual(
            [
                make_image(param, purpose)
                for param in params
                for purpose in purposes
            ],
            self.get())

    def test_returns_boot_images_on_all_clusters(self):
        factory.make_NodeGroup().accept()
        factory.make_NodeGroup().accept()
        factory.make_NodeGroup().accept()
        self.useFixture(RunningClusterRPCFixture())

        images = [make_rpc_boot_image() for _ in range(3)]
        available_images = list(images)
        available_images.pop()

        clients = getAllClients()
        for index, client in enumerate(clients):
            callRemote = self.patch(client._conn, "callRemote")
            if index == 0:
                # The first client returns all images.
                callRemote.return_value = succeed({'images': images})
            else:
                # All clients but the first return only available images.
                callRemote.return_value = succeed({'images': available_images})

        expected_images = images if self.all else available_images
        self.assertItemsEqual(expected_images, self.get())

    def test_ignores_failures_when_talking_to_clusters(self):
        factory.make_NodeGroup().accept()
        factory.make_NodeGroup().accept()
        factory.make_NodeGroup().accept()
        self.useFixture(RunningClusterRPCFixture())

        images = [make_rpc_boot_image() for _ in range(3)]

        clients = getAllClients()
        for index, client in enumerate(clients):
            callRemote = self.patch(client._conn, "callRemote")
            if index == 0:
                # The first client returns correct image information.
                callRemote.return_value = succeed({'images': images})
            else:
                # All clients but the first raise an exception.
                callRemote.side_effect = ZeroDivisionError()

        self.assertItemsEqual(images, self.get())

    def test_returns_empty_list_when_all_clusters_fail(self):
        factory.make_NodeGroup().accept()
        factory.make_NodeGroup().accept()
        factory.make_NodeGroup().accept()
        self.useFixture(RunningClusterRPCFixture())

        clients = getAllClients()
        for index, client in enumerate(clients):
            callRemote = self.patch(client._conn, "callRemote")
            callRemote.side_effect = ZeroDivisionError()

        self.assertItemsEqual([], self.get())


class TestGetBootImagesFor(MAASServerTestCase):
    """Tests for `get_boot_images_for`."""

    def setUp(self):
        super(TestGetBootImagesFor, self).setUp()
        prepare_tftp_root(self)  # Sets self.tftp_root.

    def make_boot_images(self):
        purposes = ['install', 'commissioning', 'xinstall']
        params = [make_boot_image_storage_params() for _ in range(3)]
        for param in params:
            make_image_dir(param, self.tftp_root)
            test_tftppath.make_osystem(self, param['osystem'], purposes)
        return params

    def make_rpc_boot_images(self, param):
        purposes = ['install', 'commissioning', 'xinstall']
        return [
            make_image(param, purpose)
            for purpose in purposes
            ]

    def test_returns_boot_images_matching_subarchitecture(self):
        nodegroup = factory.make_NodeGroup(status=NODEGROUP_STATUS.ENABLED)
        self.useFixture(RunningClusterRPCFixture())
        params = self.make_boot_images()
        param = params.pop()

        self.assertItemsEqual(
            self.make_rpc_boot_images(param),
            get_boot_images_for(
                nodegroup,
                param['osystem'],
                param['architecture'],
                param['subarchitecture'],
                param['release']))

    def test_returns_boot_images_matching_subarches_in_boot_resources(self):
        nodegroup = factory.make_NodeGroup(status=NODEGROUP_STATUS.ENABLED)
        self.useFixture(RunningClusterRPCFixture())
        params = self.make_boot_images()
        param = params.pop()

        subarches = [factory.make_name('subarch') for _ in range(3)]
        resource_name = '%s/%s' % (param['osystem'], param['release'])
        resource_arch = '%s/%s' % (
            param['architecture'], param['subarchitecture'])

        resource = factory.make_BootResource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED,
            name=resource_name, architecture=resource_arch)
        resource.extra['subarches'] = ','.join(subarches)
        resource.save()

        subarch = subarches.pop()
        self.assertItemsEqual(
            self.make_rpc_boot_images(param),
            get_boot_images_for(
                nodegroup,
                param['osystem'],
                param['architecture'],
                subarch,
                param['release']))