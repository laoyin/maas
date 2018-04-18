# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Event-loop support for the MAAS Region Controller.

This helps start up a background event loop (using Twisted, via crochet)
to handle communications with Cluster Controllers, and any other tasks
that are not tied to an HTTP reqoest.

.. py:data:: loop

   The single instance of :py:class:`RegionEventLoop` that's all a
   process needs.

.. py:data:: services

   The :py:class:`~twisted.application.service.MultiService` which forms
   the root of this process's service tree.

   This is a convenient reference to :py:attr:`.loop.services`.

.. py:data:: start

   Start all the services in :py:data:`services`.

   This is a convenient reference to :py:attr:`.loop.start`.

.. py:data:: stop

   Stop all the services in :py:data:`services`.

   This is a convenient reference to :py:attr:`.loop.stop`.

"""

__all__ = [
    "loop",
    "reset",
    "services",
    "start",
    "stop",
]

from logging import getLogger
import os
import socket
from socket import gethostname

from maasserver.utils.orm import disable_all_database_connections
from provisioningserver.utils.twisted import asynchronous
from twisted.application.service import (
    MultiService,
    Service,
)
from twisted.internet import reactor
from twisted.internet.defer import (
    DeferredList,
    inlineCallbacks,
    maybeDeferred,
)
from twisted.internet.endpoints import AdoptedStreamServerEndpoint

# Default port for regiond.
DEFAULT_PORT = 5240

logger = getLogger(__name__)


reactor.addSystemEventTrigger(
    "before", "startup", disable_all_database_connections)


def make_DatabaseTaskService():
    from maasserver.utils import dbtasks
    return dbtasks.DatabaseTasksService()


def make_RegionControllerService(postgresListener):
    from maasserver.region_controller import RegionControllerService
    return RegionControllerService(postgresListener)


def make_RegionService(advertiser):
    # Import here to avoid a circular import.
    from maasserver.rpc import regionservice
    return regionservice.RegionService(advertiser)


def make_RegionAdvertisingService():
    # Import here to avoid a circular import.
    from maasserver.rpc import regionservice
    return regionservice.RegionAdvertisingService()


def make_NonceCleanupService():
    from maasserver import nonces_cleanup
    return nonces_cleanup.NonceCleanupService()


def make_DNSPublicationGarbageService():
    from maasserver.dns import publication
    return publication.DNSPublicationGarbageService()


def make_StatusMonitorService():
    from maasserver import status_monitor
    return status_monitor.StatusMonitorService()


def make_StatsService():
    from maasserver import stats
    return stats.StatsService()


def make_ImportResourcesService():
    from maasserver import bootresources
    return bootresources.ImportResourcesService()


def make_ImportResourcesProgressService():
    from maasserver import bootresources
    return bootresources.ImportResourcesProgressService()


def make_PostgresListenerService():
    from maasserver.listener import PostgresListenerService
    return PostgresListenerService()


def make_RackControllerService(postgresListener, advertisingService):
    from maasserver.rack_controller import RackControllerService
    return RackControllerService(postgresListener, advertisingService)


def make_StatusWorkerService(dbtasks):
    from metadataserver.api_twisted import StatusWorkerService
    return StatusWorkerService(dbtasks)


def make_ServiceMonitorService(advertisingService):
    from maasserver.regiondservices import service_monitor_service
    return service_monitor_service.ServiceMonitorService(advertisingService)


def make_NetworksMonitoringService():
    from maasserver.regiondservices.networks_monitoring import (
        RegionNetworksMonitoringService,
    )
    return RegionNetworksMonitoringService(reactor)


def make_ActiveDiscoveryService(postgresListener):
    from maasserver.regiondservices.active_discovery import (
        ActiveDiscoveryService
    )
    return ActiveDiscoveryService(reactor, postgresListener)


def make_ReverseDNSService(postgresListener):
    from maasserver.regiondservices.reverse_dns import (
        ReverseDNSService
    )
    return ReverseDNSService(postgresListener)


def make_NetworkTimeProtocolService():
    from maasserver.regiondservices import ntp
    return ntp.RegionNetworkTimeProtocolService(reactor)


def make_WebApplicationService(postgresListener, statusWorker):
    from maasserver.webapp import WebApplicationService
    site_port = DEFAULT_PORT  # config["port"]
    # Make a socket with SO_REUSEPORT set so that we can run multiple web
    # applications. This is easier to do from outside of Twisted as there's
    # not yet official support for setting socket options.
    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    # N.B, using the IPv6 INADDR_ANY means that getpeername() returns something
    # like: ('::ffff:192.168.133.32', 40588, 0, 0)
    s.bind(('::', site_port))
    # Use a backlog of 50, which seems to be fairly common.
    s.listen(50)
    # Adopt this socket into Twisted's reactor.
    site_endpoint = AdoptedStreamServerEndpoint(reactor, s.fileno(), s.family)
    site_endpoint.port = site_port  # Make it easy to get the port number.
    site_endpoint.socket = s  # Prevent garbage collection.
    site_service = WebApplicationService(
        site_endpoint, postgresListener, statusWorker)
    return site_service


def make_WorkersService():
    from maasserver.workers import WorkersService
    return WorkersService(reactor)


def make_IPCMasterService(workers=None):
    from maasserver.ipc import IPCMasterService
    return IPCMasterService(reactor, workers)


def make_IPCWorkerService():
    from maasserver.ipc import IPCWorkerService
    return IPCWorkerService(reactor)


class MAASServices(MultiService):

    def __init__(self, eventloop):
        self.eventloop = eventloop
        super().__init__()

    @asynchronous
    @inlineCallbacks
    def startService(self):
        yield maybeDeferred(self.eventloop.prepare)
        Service.startService(self)
        yield DeferredList([
            maybeDeferred(service.startService)
            for service in self
        ])


class RegionEventLoop:
    """An event loop running in a region controller process.

    Typically several processes will be running the web application --
    chiefly Django -- across several machines, with multiple threads of
    execution in each processingle event loop for each *process*,
    allowing convenient control of the event loop -- a Twisted reactor
    running in a thread -- and to which to attach and query services.

    :cvar factories: A sequence of ``(name, factory)`` tuples. Used to
        populate :py:attr:`.services` at start time.

    :ivar services:
        A :py:class:`~twisted.application.service.MultiService` which
        forms the root of the service tree.

    """

    factories = {
        "database-tasks": {
            "only_on_master": False,
            "factory": make_DatabaseTaskService,
            "requires": [],
        },
        "region-controller": {
            "only_on_master": True,
            "factory": make_RegionControllerService,
            "requires": ["postgres-listener-master"],
        },
        "rpc": {
            "only_on_master": False,
            "factory": make_RegionService,
            "requires": ["rpc-advertise"],
        },
        "rpc-advertise": {
            "only_on_master": False,
            "factory": make_RegionAdvertisingService,
            "requires": [],
        },
        "nonce-cleanup": {
            "only_on_master": True,
            "factory": make_NonceCleanupService,
            "requires": [],
        },
        "dns-publication-cleanup": {
            "only_on_master": True,
            "factory": make_DNSPublicationGarbageService,
            "requires": [],
        },
        "status-monitor": {
            "only_on_master": True,
            "factory": make_StatusMonitorService,
            "requires": [],
        },
        "stats": {
            "only_on_master": True,
            "factory": make_StatsService,
            "requires": [],
        },
        "import-resources": {
            "only_on_master": True,
            "factory": make_ImportResourcesService,
            "requires": [],
        },
        "import-resources-progress": {
            "only_on_master": True,
            "factory": make_ImportResourcesProgressService,
            "requires": [],
        },
        "postgres-listener-master": {
            "only_on_master": True,
            "factory": make_PostgresListenerService,
            "requires": [],
        },
        "postgres-listener-worker": {
            "only_on_master": False,
            "factory": make_PostgresListenerService,
            "requires": [],
        },
        "web": {
            "only_on_master": False,
            "factory": make_WebApplicationService,
            "requires": ["postgres-listener-worker", "status-worker"],
        },
        "service-monitor": {
            "only_on_master": False,
            "factory": make_ServiceMonitorService,
            "requires": ["rpc-advertise"],
        },
        "status-worker": {
            "only_on_master": False,
            "factory": make_StatusWorkerService,
            "requires": ["database-tasks"],
        },
        "networks-monitor": {
            "only_on_master": True,
            "factory": make_NetworksMonitoringService,
            "requires": [],
        },
        "active-discovery": {
            "only_on_master": True,
            "factory": make_ActiveDiscoveryService,
            "requires": ["postgres-listener-master"],
        },
        "reverse-dns": {
            "only_on_master": True,
            "factory": make_ReverseDNSService,
            "requires": ["postgres-listener-master"],
        },
        "rack-controller": {
            "only_on_master": False,
            "factory": make_RackControllerService,
            "requires": ["postgres-listener-worker", "rpc-advertise"],
        },
        "ntp": {
            "only_on_master": True,
            "factory": make_NetworkTimeProtocolService,
            "requires": [],
        },
        "workers": {
            "only_on_master": True,
            "not_all_in_one": True,
            "factory": make_WorkersService,
            "requires": [],
        },
        "ipc-master": {
            "only_on_master": True,
            "factory": make_IPCMasterService,
            "requires": [],
            "optional": ["workers"],
        },
        "ipc-worker": {
            "only_on_master": False,
            "factory": make_IPCWorkerService,
            "requires": [],
        },
    }


    # factories = {
    #     "postgres-listener-worker": {
    #         "only_on_master": False,
    #         "factory": make_PostgresListenerService,
    #         "requires": [],
    #     },
    #     "web": {
    #         "only_on_master": False,
    #         "factory": make_WebApplicationService,
    #         "requires": ["postgres-listener-worker", "status-worker"],
    #     },
    #     "status-worker": {
    #         "only_on_master": False,
    #         "factory": make_StatusWorkerService,
    #         "requires": ["database-tasks"],
    #     },
    #     "database-tasks": {
    #         "only_on_master": False,
    #         "factory": make_DatabaseTaskService,
    #         "requires": [],
    #     },
    #     "rpc": {
    #         "only_on_master": False,
    #         "factory": make_RegionService,
    #         "requires": ["rpc-advertise"],
    #     },
    #     "rpc-advertise": {
    #         "only_on_master": False,
    #         "factory": make_RegionAdvertisingService,
    #         "requires": [],
    #     },
    # }

    def __init__(self):
        super(RegionEventLoop, self).__init__()
        self.services = MAASServices(self)
        self.handle = None
        self.master = False

    @asynchronous
    def populateService(self, name, master=False, all_in_one=False):
        """Prepare a service."""
        factoryInfo = self.factories[name]
        if not all_in_one:
            if factoryInfo["only_on_master"] and not master:
                raise ValueError(
                    "Service '%s' cannot be created because it can only run "
                    "on the master process." % name)
            elif not factoryInfo["only_on_master"] and master:
                raise ValueError(
                    "Service '%s' cannot be created because it can only run "
                    "on a worker process." % name)
        else:
            dont_run = factoryInfo.get('not_all_in_one', False)
            if dont_run:
                raise ValueError(
                    "Service '%s' cannot be created because it can not run "
                    "in the all-in-one process." % name)
        try:
            service = self.services.getServiceNamed(name)
        except KeyError:
            # Get all dependent services for this services.
            dependencies = []
            optional_args = {}
            for require in factoryInfo["requires"]:
                dependencies.append(
                    self.populateService(
                        require, master=master, all_in_one=all_in_one))
            for optional in factoryInfo.get("optional", []):
                try:
                    service = self.populateService(
                        optional, master=master, all_in_one=all_in_one)
                except ValueError:
                    pass
                else:
                    optional_args[optional] = service

            # Create the service with dependencies.
            service = factoryInfo["factory"](*dependencies, **optional_args)
            service.setName(name)
            service.setServiceParent(self.services)
        return service

    @asynchronous
    def populate(self, master=False, all_in_one=False):
        """Prepare services."""
        self.master = master
        for name, item in self.factories.items():
            if all_in_one:
                if not item.get('not_all_in_one', False):
                    self.populateService(
                        name, master=master, all_in_one=all_in_one)
            else:
                if item['only_on_master'] and master:
                    self.populateService(
                        name, master=master, all_in_one=all_in_one)
                elif not item['only_on_master'] and not master:
                    self.populateService(
                        name, master=master, all_in_one=all_in_one)

    @asynchronous
    def prepare(self):
        """Perform start_up of the region process."""
        from maasserver.start_up import start_up
        return start_up(self.master)

    @asynchronous
    def startMultiService(self, result):
        """Start the multi service."""
        self.services.startService()

    @asynchronous
    def start(self):
        """start()

        Start all services in the region's event-loop.
        """
        self.populate()
        self.handle = reactor.addSystemEventTrigger(
            'before', 'shutdown', self.services.stopService)
        return self.prepare().addCallback(
            self.startMultiService)

    @asynchronous
    def stop(self):
        """stop()

        Stop all services in the region's event-loop.
        """
        if self.handle is not None:
            handle, self.handle = self.handle, None
            reactor.removeSystemEventTrigger(handle)
        return self.services.stopService()

    @asynchronous
    def reset(self):
        """reset()

        Stop all services, then disown them all.
        """
        def disown_all_services(_):
            for service in list(self.services):
                service.disownServiceParent()

        def reset_factories(_):
            try:
                # Unshadow class attribute.
                del self.factories
            except AttributeError:
                # It wasn't shadowed.
                pass

        d = self.stop()
        d.addCallback(disown_all_services)
        d.addCallback(reset_factories)
        return d

    @property
    def name(self):
        """A name for identifying this service in a distributed system."""
        return "%s:pid=%d" % (gethostname(), os.getpid())

    @property
    def running(self):
        """Is this running?"""
        return bool(self.services.running)


loop = RegionEventLoop()
reset = loop.reset
services = loop.services
start = loop.start
stop = loop.stop
