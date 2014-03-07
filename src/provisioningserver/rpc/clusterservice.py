# Copyright 2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""RPC implementation for clusters."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    "ClusterClientService",
    "ClusterService",
]

import json
import random
from urlparse import urlparse

from apiclient.utils import ascii_url
from provisioningserver.cluster_config import (
    get_cluster_uuid,
    get_maas_url,
    )
from provisioningserver.config import Config
from provisioningserver.driver import ArchitectureRegistry
from provisioningserver.power_schema import JSON_POWER_TYPE_PARAMETERS
from provisioningserver.pxe import tftppath
from provisioningserver.rpc import (
    cluster,
    common,
    exceptions,
    region,
    )
from provisioningserver.rpc.interfaces import IConnection
from twisted.application.internet import (
    StreamServerEndpointService,
    TimerService,
    )
from twisted.internet import ssl
from twisted.internet.defer import inlineCallbacks
from twisted.internet.endpoints import (
    connectProtocol,
    TCP4ClientEndpoint,
    TCP4ServerEndpoint,
    )
from twisted.internet.error import ConnectError
from twisted.internet.protocol import Factory
from twisted.protocols import amp
from twisted.python import (
    filepath,
    log,
    )
from twisted.web.client import getPage
from zope.interface import implementer


class Cluster(amp.AMP, object):
    """The RPC protocol supported by a cluster controller.

    This can be used on the client or server end of a connection; once a
    connection is established, AMP is symmetric.
    """

    @cluster.Identify.responder
    def identify(self):
        """identify()

        Implementation of
        :py:class:`~provisioningserver.rpc.cluster.Identify`.
        """
        return {b"ident": get_cluster_uuid().decode("ascii")}

    @cluster.ListBootImages.responder
    def list_boot_images(self):
        """list_boot_images()

        Implementation of
        :py:class:`~provisioningserver.rpc.cluster.ListBootImages`.
        """
        images = tftppath.list_boot_images(
            Config.load_from_cache()['tftp']['root'])
        return {"images": images}

    @cluster.DescribePowerTypes.responder
    def describe_power_types(self):
        """describe_power_types()

        Implementation of
        :py:class:`~provisioningserver.rpc.cluster.DescribePowerTypes`.
        """
        return {'power_types': JSON_POWER_TYPE_PARAMETERS}

    @cluster.ListSupportedArchitectures.responder
    def list_supported_architectures(self):
        return {
            'architectures': [
                {'name': arch.name, 'description': arch.description}
                for arch in ArchitectureRegistry.get_items()
                ],
            }

    @amp.StartTLS.responder
    def get_tls_parameters(self):
        """get_tls_parameters()

        Implementation of :py:class:`~twisted.protocols.amp.StartTLS`.
        """
        # TODO: Obtain certificates from a config store.
        testing = filepath.FilePath(__file__).sibling("testing")
        with testing.child("cluster.crt").open() as fin:
            tls_localCertificate = ssl.PrivateCertificate.loadPEM(fin.read())
        with testing.child("trust.crt").open() as fin:
            tls_verifyAuthorities = [
                ssl.Certificate.loadPEM(fin.read()),
            ]
        return {
            "tls_localCertificate": tls_localCertificate,
            "tls_verifyAuthorities": tls_verifyAuthorities,
        }


class ClusterService(StreamServerEndpointService):
    """A cluster controller RPC service.

    This is a service - in the Twisted sense - that exposes the
    ``Cluster`` protocol on the given port.
    """

    def __init__(self, reactor, port):
        super(ClusterService, self).__init__(
            TCP4ServerEndpoint(reactor, port),
            Factory.forProtocol(Cluster))


@implementer(IConnection)
class ClusterClient(Cluster):
    """The RPC protocol supported by a cluster controller, client version.

    This works hand-in-hand with ``ClusterClientService``, maintaining
    the latter's `connections` map.

    :ivar address: The `(host, port)` of the remote endpoint.

    :ivar eventloop: The event-loop this client is related to.

    :ivar service: A reference to the :class:`ClusterClientService` that
        made self.

    """

    address = None
    eventloop = None
    service = None

    def __init__(self, address, eventloop, service):
        super(ClusterClient, self).__init__()
        self.address = address
        self.eventloop = eventloop
        self.service = service

    @property
    def ident(self):
        """The ident of the remote event-loop."""
        return self.eventloop

    def connectionMade(self):
        super(ClusterClient, self).connectionMade()
        if not self.service.running:
            self.transport.loseConnection()
        elif self.eventloop in self.service.connections:
            self.transport.loseConnection()
        else:
            self.service.connections[self.eventloop] = self

    def connectionLost(self, reason):
        if self.eventloop in self.service.connections:
            if self.service.connections[self.eventloop] is self:
                del self.service.connections[self.eventloop]
        super(ClusterClient, self).connectionLost(reason)

    @inlineCallbacks
    def secureConnection(self):
        yield self.callRemote(amp.StartTLS, **self.get_tls_parameters())

        # For some weird reason (it's mentioned in Twisted's source),
        # TLS negotiation does not complete until we do something with
        # the connection. Here we check that the remote event-loop is
        # who we expected it to be.
        response = yield self.callRemote(region.Identify)
        remote_name = response.get("name")
        if remote_name != self.eventloop:
            log.msg(
                "The remote event-loop identifies itself as %s, but "
                "%s was expected." % (remote_name, self.eventloop))
            self.transport.loseConnection()
            return

        # We should now have a full set of parameters for the transport.
        log.msg("Host certificate: %r" % self.hostCertificate)
        log.msg("Peer certificate: %r" % self.peerCertificate)


class ClusterClientService(TimerService, object):
    """A cluster controller RPC client service.

    This is a service - in the Twisted sense - that connects to a set of
    remote AMP endpoints. The endpoints are obtained from a view in the
    region controller and periodically refreshed; this list is used to
    update the connections maintained in this service.

    :ivar connections: A mapping of eventloop names to protocol
        instances connected to it.
    """

    def __init__(self, reactor):
        super(ClusterClientService, self).__init__(
            self._get_random_interval(), self.update)
        self.connections = {}
        self.clock = reactor

    def getClient(self):
        """Returns a :class:`common.Client` connected to a region.

        The client is chosen at random.

        :raises: :py:class:`~.exceptions.NoConnectionsAvailable` when
            there are no open connections to a region controller.
        """
        conns = list(self.connections.viewvalues())
        if len(conns) == 0:
            raise exceptions.NoConnectionsAvailable()
        else:
            return common.Client(random.choice(conns))

    @inlineCallbacks
    def update(self):
        """Refresh outgoing connections.

        This obtains a list of endpoints from the region then connects
        to new ones and drops connections to those no longer used.
        """
        # 0. Update interval.
        self._update_interval()
        # 1. Obtain RPC endpoints.
        try:
            info_url = self._get_rpc_info_url()
            info_page = yield getPage(info_url)
            info = json.loads(info_page)
            eventloops = info["eventloops"]
            yield self._update_connections(eventloops)
        except:
            log.err()

    @staticmethod
    def _get_rpc_info_url():
        """Return the URL to the RPC infomation page on the region."""
        url = urlparse(get_maas_url())
        url = url._replace(path="%s/rpc/" % url.path.rstrip("/"))
        url = url.geturl()
        return ascii_url(url)

    @staticmethod
    def _get_random_interval():
        """Return a random interval between 30 and 90 seconds."""
        return random.randint(30, 90)

    def _update_interval(self):
        """Change the interval randomly to avoid stampedes of clusters."""
        self._loop.interval = self.step = self._get_random_interval()

    @inlineCallbacks
    def _update_connections(self, eventloops):
        """Update the persistent connections to the region.

        For each event-loop, ensure that there is (a) a connection
        established and that (b) that connection corresponds to one of
        the endpoints declared. If not (a), attempt to connect to each
        endpoint in turn. If not (b), immediately drop the connection
        and proceed as if not (a).

        For each established connection to an event-loop, check that
        it's still in the list of event-loops to which this cluster
        should connect. If not, immediately drop the connection.
        """
        # Ensure that the event-loop addresses are tuples so that
        # they'll work as dictionary keys.
        eventloops = {
            name: [tuple(address) for address in addresses]
            for name, addresses in eventloops.iteritems()
        }
        # Drop connections to event-loops that no longer include one of
        # this cluster's established connections among its advertised
        # endpoints. This is most likely to have happened because of
        # network reconfiguration on the machine hosting the event-loop,
        # and so the connection may have dropped already, but there's
        # nothing wrong with a bit of belt-and-braces engineering
        # between consenting adults.
        for eventloop, addresses in eventloops.iteritems():
            if eventloop in self.connections:
                connection = self.connections[eventloop]
                if connection.address not in addresses:
                    yield self._drop_connection(connection)
        # Create new connections to event-loops that the cluster does
        # not yet have a connection to. Try each advertised endpoint
        # (address) in turn until one of them bites.
        for eventloop, addresses in eventloops.iteritems():
            if eventloop not in self.connections:
                for address in addresses:
                    try:
                        yield self._make_connection(eventloop, address)
                    except ConnectError as error:
                        host, port = address
                        log.msg("Event-loop %s (%s:%d): %s" % (
                            eventloop, host, port, error))
                    except:
                        log.err()
                    else:
                        break
        # Remove connections to event-loops that are no longer
        # advertised by the RPC info view. Most likely this means that
        # the process in which the event-loop is no longer running, but
        # it could be an indicator of a heavily loaded machine, or a
        # fault. In any case, it seems to make sense to disconnect.
        for eventloop in self.connections:
            if eventloop not in eventloops:
                connection = self.connections[eventloop]
                yield self._drop_connection(connection)

    def _make_connection(self, eventloop, address):
        """Connect to `eventloop` at `address`."""
        endpoint = TCP4ClientEndpoint(self.clock, *address)
        protocol = ClusterClient(address, eventloop, self)
        return connectProtocol(endpoint, protocol)

    def _drop_connection(self, connection):
        """Drop the given `connection`."""
        return connection.transport.loseConnection()
