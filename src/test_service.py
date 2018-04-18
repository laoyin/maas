# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Entrypoint for the maas rackd service."""

# Install the asyncio reactor with uvloop. This must be done before any other
# twisted code is imported.
import asyncio
import sys
import pdb


import signal
import time

from provisioningserver import logger
from provisioningserver.logger import LegacyLogger
from provisioningserver.utils.debug import (
    register_sigusr2_thread_dump_handler,
)
from twisted.application.service import IServiceMaker
from twisted.internet import reactor
from twisted.plugin import IPlugin
from twisted.python.threadable import isInIOThread
from zope.interface import implementer


from twisted.python import usage
from twisted.scripts._twistd_unix import ServerOptions, UnixApplicationRunner


import twisted.internet
from twisted.internet import asyncioreactor


try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

# Force install the reactor. In some cases some pre-initialization code will
# create the wrong reactor. This ensures that its always the asyncio reactor.
reactor = asyncioreactor.AsyncioSelectorReactor()
twisted.internet.reactor = reactor
sys.modules['twisted.internet.reactor'] = reactor




# Load the available MAAS plugins.
twistd_plugins = []
try:
    from provisioningserver.plugin import ProvisioningServiceMaker
except ImportError:
    pass
else:
    # Rackd service that twisted will spawn.
    twistd_plugins.append(
        ProvisioningServiceMaker(
            "maas-rackd", "The MAAS Rack Controller daemon."))

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


# Default port for regiond.
DEFAULT_PORT = 5240

reactor.addSystemEventTrigger(
    "before", "startup", disable_all_database_connections)


def make_ActiveDiscoveryService(postgresListener):
    from maasserver.regiondservices.active_discovery import (
        ActiveDiscoveryService
    )
    return ActiveDiscoveryService(reactor, postgresListener)

def make_PostgresListenerService():
    from maasserver.listener import PostgresListenerService
    return PostgresListenerService()


def make_ReverseDNSService(postgresListener):
    from maasserver.regiondservices.reverse_dns import (
        ReverseDNSService
    )
    return ReverseDNSService(postgresListener)

from twisted.internet.endpoints import AdoptedStreamServerEndpoint
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


def make_StatusWorkerService(dbtasks):
    from metadataserver.api_twisted import StatusWorkerService
    return StatusWorkerService(dbtasks)

def make_DatabaseTaskService():
    from maasserver.utils import dbtasks
    return dbtasks.DatabaseTasksService()

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
        "active-discovery": {
            "factory": make_ActiveDiscoveryService,
            "requires": ["postgres-listener-master"],
        },
        "postgres-listener-worker": {
            "factory": make_PostgresListenerService,
            "requires": [],
        },
        "postgres-listener-master": {
            "only_on_master": True,
            "factory": make_PostgresListenerService,
            "requires": [],
        },
        "reverse-dns": {
            "only_on_master": True,
            "factory": make_ReverseDNSService,
            "requires": ["postgres-listener-master"],
        },
        "web": {
            "only_on_master": False,
            "factory": make_WebApplicationService,
            "requires": ["postgres-listener-worker", "status-worker"],
        },
        "status-worker": {
            "only_on_master": False,
            "factory": make_StatusWorkerService,
            "requires": ["database-tasks"],
        },
        "database-tasks": {
            "only_on_master": False,
            "factory": make_DatabaseTaskService,
            "requires": [],
        },
    }

    def __init__(self):
        super(RegionEventLoop, self).__init__()
        self.services = MAASServices(self)
        self.handle = None
        self.master = False

    @asynchronous
    def populateService(self, name, master=False, all_in_one=False):
        """Prepare a service."""
        factoryInfo = self.factories[name]
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
            self.populateService(name, master=master, all_in_one=all_in_one)

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


testloop = RegionEventLoop()
reset = testloop.reset
services = testloop.services
start = testloop.start
stop = testloop.stop


log = LegacyLogger()


class Options(logger.VerbosityOptions):
    """Command-line options for `regiond`."""


@implementer(IServiceMaker, IPlugin)
class RegionWorkerServiceMaker:
    """Create the worker service for the Twisted plugin."""

    options = Options

    def __init__(self, name, description):
        self.tapname = name
        self.description = description

    def _set_pdeathsig(self):
        # Worker must die when the the master dies, no exceptions, no hanging
        # around so it must be killed.
        #
        # Sadly the only way to do this in python is to use ctypes. This tells
        # the kernel that when my parent dies to kill me.
        import ctypes
        libc = ctypes.CDLL("libc.so.6")
        libc.prctl(1, signal.SIGKILL)

    def _configureThreads(self):
        from maasserver.utils import threads
        threads.install_default_pool()
        threads.install_database_pool()

    def _configureLogging(self, verbosity: int):
        # Get something going with the logs.
        logger.configure(verbosity, logger.LoggingMode.TWISTD)

    def _configureDjango(self):
        # Some region services use the ORM at class-load time: force Django to
        # load the models first. This is OK to run in the reactor because
        # having Django -- most specifically the ORM -- up and running is a
        # prerequisite of almost everything in the region controller.
        import django
        django.setup()

    def _configureReactor(self):
        # Disable all database connections in the reactor.
        from maasserver.utils.orm import disable_all_database_connections
        if isInIOThread():
            disable_all_database_connections()
        else:
            reactor.callFromThread(disable_all_database_connections)

    def _configureCrochet(self):
        # Prevent other libraries from starting the reactor via crochet.
        # In other words, this makes crochet.setup() a no-op.
        import crochet
        crochet.no_setup()

    def makeService(self, options):
        """Construct the MAAS Region service."""
        register_sigusr2_thread_dump_handler()

        self._set_pdeathsig()
        self._configureThreads()
        self._configureLogging(options["verbosity"])
        self._configureDjango()
        self._configureReactor()
        self._configureCrochet()

        # Populate the region's event-loop with services.
        testloop.populate(master=False)

        # Return the eventloop's services to twistd, which will then be
        # responsible for starting them all.
        return testloop.services


@implementer(IServiceMaker, IPlugin)
class RegionMasterServiceMaker(RegionWorkerServiceMaker):
    """Create the master service for the Twisted plugin."""

    options = Options

    def __init__(self, name, description):
        self.tapname = name
        self.description = description

    def _ensureConnection(self):
        # If connection is already made close it.
        from django.db import connection
        if connection.connection is not None:
            connection.close()

        # Loop forever until a connection can be made.
        while True:
            try:
                connection.ensure_connection()
            except Exception:
                log.err(_why=(
                    "Error starting: "
                    "Connection to database cannot be established."))
                time.sleep(1)
            else:
                # Connection made, now close it.
                connection.close()
                break

    def makeService(self, options):
        """Construct the MAAS Region service."""
        register_sigusr2_thread_dump_handler()

        self._configureThreads()
        self._configureLogging(options["verbosity"])
        self._configureDjango()
        self._configureReactor()
        self._configureCrochet()
        self._ensureConnection()

        # Populate the region's event-loop with services.
        from maasserver import eventloop
        testloop.populate(master=True)

        # Return the eventloop's services to twistd, which will then be
        # responsible for starting them all.
        return testloop.services


@implementer(IServiceMaker, IPlugin)
class RegionAllInOneServiceMaker(RegionMasterServiceMaker):
    """Create the all-in-one service for the Twisted plugin.

    This service runs all the Twisted services in the same process, instead
    of forking the workers.
    """

    options = Options

    def __init__(self, name, description):
        self.tapname = name
        self.description = description

    def makeService(self, options):
        """Construct the MAAS Region service."""
        register_sigusr2_thread_dump_handler()

        self._configureThreads()
        self._configureLogging(options["verbosity"])
        self._configureDjango()
        self._configureReactor()
        self._configureCrochet()
        self._ensureConnection()

        # Populate the region's event-loop with services.
        testloop.populate(master=True, all_in_one=True)

        # Return the eventloop's services to twistd, which will then be
        # responsible for starting them all.
        return testloop.services


# Regiond services that twisted could spawn.
twistd_plugins.append(
    RegionAllInOneServiceMaker(
        "xingpan_test",
        "xingpan test all server online"))


class SOptions(ServerOptions):
    """Override the plugins path for the server options."""

    @staticmethod
    def _getPlugins(interface):
        return twistd_plugins


def runService(service):
    """Run the `service`."""
    config = SOptions()
    args = [
        '--logger=provisioningserver.logger.EventLogger',
        '--nodaemon', '--pidfile=',
    ]
    args += sys.argv[1:]
    args += [service]
    try:
        config.parseOptions(args)
    except usage.error as exc:
        print(config)
        print("%s: %s" % (sys.argv[0], exc))
    else:
        UnixApplicationRunner(config).run()


def run():
    """Run xingpan test"""
    import pdb
    runService('xingpan_test')


if __name__ == "__main__":
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE", "maasserver.djangosettings.settings")
    os.environ.setdefault(
        "/snap/bin/rackd_server_start.py", "/home/pan/qinyun/maas/src/rackd_server_start.py")
    from maasserver.monkey import fix_django_big_auto_field
    # fix django version problem
    fix_django_big_auto_field()
    run()