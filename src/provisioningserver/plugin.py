# Copyright 2012-2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Twisted Application Plugin code for the MAAS provisioning server"""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []

import provisioningserver
from provisioningserver.amqpclient import AMQFactory
from provisioningserver.cluster_config import get_cluster_uuid
from provisioningserver.config import Config
from provisioningserver.image_download_service import (
    PeriodicImageDownloadService,
    )
from provisioningserver.rpc.clusterservice import ClusterClientService
from provisioningserver.services import (
    LogService,
    OOPSService,
    )
from provisioningserver.tftp import TFTPService
from twisted.application.internet import (
    TCPClient,
    TCPServer,
    )
from twisted.application.service import (
    IServiceMaker,
    MultiService,
    )
from twisted.cred.checkers import ICredentialsChecker
from twisted.cred.credentials import IUsernamePassword
from twisted.cred.error import UnauthorizedLogin
from twisted.cred.portal import IRealm
from twisted.internet import reactor
from twisted.internet.defer import (
    inlineCallbacks,
    returnValue,
    )
from twisted.plugin import IPlugin
from twisted.python import (
    log,
    usage,
    )
from twisted.web.resource import (
    IResource,
    Resource,
    )
from twisted.web.server import Site
from zope.interface import implementer


@implementer(ICredentialsChecker)
class SingleUsernamePasswordChecker:
    """An `ICredentialsChecker` for a single username and password."""

    credentialInterfaces = [IUsernamePassword]

    def __init__(self, username, password):
        super(SingleUsernamePasswordChecker, self).__init__()
        self.username = username
        self.password = password

    @inlineCallbacks
    def requestAvatarId(self, credentials):
        """See `ICredentialsChecker`."""
        if credentials.username == self.username:
            matched = yield credentials.checkPassword(self.password)
            if matched:
                returnValue(credentials.username)
        raise UnauthorizedLogin(credentials.username)


@implementer(IRealm)
class ProvisioningRealm:
    """The `IRealm` for the Provisioning API."""

    noop = staticmethod(lambda: None)

    def __init__(self, resource):
        super(ProvisioningRealm, self).__init__()
        self.resource = resource

    def requestAvatar(self, avatarId, mind, *interfaces):
        """See `IRealm`."""
        if IResource in interfaces:
            return (IResource, self.resource, self.noop)
        raise NotImplementedError()


class Options(usage.Options):
    """Command line options for the provisioning server."""

    optParameters = [
        ["config-file", "c", "pserv.yaml", "Configuration file to load."],
        ]


@implementer(IServiceMaker, IPlugin)
class ProvisioningServiceMaker(object):
    """Create a service for the Twisted plugin."""

    options = Options

    def __init__(self, name, description):
        self.tapname = name
        self.description = description

    def _makeLogService(self, config):
        """Create the log service."""
        return LogService(config["logfile"])

    def _makeOopsService(self, log_service, oops_config):
        """Create the oops service."""
        oops_dir = oops_config["directory"]
        oops_reporter = oops_config["reporter"]
        return OOPSService(log_service, oops_dir, oops_reporter)

    def _makeSiteService(self, papi_xmlrpc, config):
        """Create the site service."""
        site_root = Resource()
        site_root.putChild("api", papi_xmlrpc)
        site = Site(site_root)
        site_port = config["port"]
        site_interface = config["interface"]
        site_service = TCPServer(site_port, site, interface=site_interface)
        site_service.setName("site")
        return site_service

    def _makeBroker(self, broker_config):
        """Create the messaging broker."""
        broker_port = broker_config["port"]
        broker_host = broker_config["host"]
        broker_username = broker_config["username"]
        broker_password = broker_config["password"]
        broker_vhost = broker_config["vhost"]

        cb_connected = lambda ignored: None  # TODO
        cb_disconnected = lambda ignored: None  # TODO
        cb_failed = lambda connector_and_reason: (
            log.err(connector_and_reason[1], "Connection failed"))
        client_factory = AMQFactory(
            broker_username, broker_password, broker_vhost,
            cb_connected, cb_disconnected, cb_failed)
        client_service = TCPClient(
            broker_host, broker_port, client_factory)
        client_service.setName("amqp")
        return client_service

    def _makeTFTPService(self, tftp_config):
        """Create the dynamic TFTP service."""
        tftp_service = TFTPService(
            resource_root=tftp_config['resource_root'],
            port=tftp_config['port'], generator=tftp_config['generator'])
        tftp_service.setName("tftp")
        return tftp_service

    def _makePeriodicImageDownloadService(self, rpc_service):
        image_download_service = PeriodicImageDownloadService(
            rpc_service, reactor, get_cluster_uuid())
        image_download_service.setName("image_download")
        return image_download_service

    def _makeRPCService(self, rpc_config):
        rpc_service = ClusterClientService(reactor)
        rpc_service.setName("rpc")
        return rpc_service

    def makeService(self, options):
        """Construct a service."""
        services = MultiService()
        config = Config.load(options["config-file"])

        log_service = self._makeLogService(config)
        log_service.setServiceParent(services)

        oops_service = self._makeOopsService(log_service, config["oops"])
        oops_service.setServiceParent(services)

        broker_config = config["broker"]
        # Connecting to RabbitMQ is not yet a required component of a running
        # MAAS installation; skip unless the password has been set explicitly.
        if broker_config["password"] != b"test":
            client_service = self._makeBroker(broker_config)
            client_service.setServiceParent(services)

        tftp_service = self._makeTFTPService(config["tftp"])
        tftp_service.setServiceParent(services)

        rpc_service = self._makeRPCService(config["rpc"])
        rpc_service.setServiceParent(services)

        image_download_service = self._makePeriodicImageDownloadService(
            rpc_service)
        image_download_service.setServiceParent(services)

        # Store a handle to the cluster services.
        provisioningserver.services = services

        return services
