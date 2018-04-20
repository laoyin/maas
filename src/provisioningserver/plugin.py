# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Twisted Application Plugin code for the MAAS provisioning server"""

__all__ = [
    "Options",
    "ProvisioningServiceMaker",
]

from errno import ENOPROTOOPT
import socket
from socket import error as socket_error

from provisioningserver import logger
from provisioningserver.config import ClusterConfiguration
from provisioningserver.monkey import (
    add_patches_to_twisted,
    add_patches_to_txtftp,
)
from provisioningserver.utils.debug import (
    register_sigusr2_thread_dump_handler,
)
from twisted.application.service import IServiceMaker
from twisted.internet import reactor
from twisted.plugin import IPlugin
from zope.interface import implementer


class Options(logger.VerbosityOptions):
    """Command line options for `rackd`."""


@implementer(IServiceMaker, IPlugin)
class ProvisioningServiceMaker:
    """Create a service for the Twisted plugin."""

    options = Options

    def __init__(self, name, description):
        self.tapname = name
        self.description = description

    def _makeImageService(self, resource_root):
        from provisioningserver.rackdservices.image import (
            BootImageEndpointService)
        from twisted.internet.endpoints import AdoptedStreamServerEndpoint
        port = 5248  # config["port"]
        # Make a socket with SO_REUSEPORT set so that we can run multiple we
        # applications. This is easier to do from outside of Twisted as there's
        # not yet official support for setting socket options.
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except socket_error as e:
            # Python's socket module was compiled using modern headers
            # thus defining SO_REUSEPORT would cause issues as it might
            # running in older kernel that does not support SO_REUSEPORT.

            # XXX andreserl 2015-04-08 bug=1441684: We need to add a warning
            # log message when we see this error, and a test for it.
            if e.errno != ENOPROTOOPT:
                raise e
        s.bind(('::', port))
        # Use a backlog of 50, which seems to be fairly common.
        s.listen(50)
        # Adopt this socket into Twisted's reactor.
        site_endpoint = AdoptedStreamServerEndpoint(
            reactor, s.fileno(), s.family)
        site_endpoint.port = port  # Make it easy to get the port number.
        site_endpoint.socket = s  # Prevent garbage collection.

        image_service = BootImageEndpointService(
            resource_root=resource_root, endpoint=site_endpoint)
        image_service.setName("image_service")
        return image_service

    def _makeTFTPService(
            self, tftp_root, tftp_port, rpc_service):
        """Create the dynamic TFTP service."""
        print("hi, iam here")
        from provisioningserver.rackdservices.tftp import TFTPService
        tftp_service = TFTPService(
            resource_root=tftp_root, port=tftp_port,
            client_service=rpc_service)
        tftp_service.setName("tftp")
        print("tftp setup, panpanapan")
        print(tftp_port)
        # *** EXPERIMENTAL ***
        # https://code.launchpad.net/~allenap/maas/tftp-offload/+merge/312146
        # If the TFTP port has been set to zero, use the experimental offload
        # service. Otherwise stick to the normal in-process TFTP service.
        if tftp_port == 0:
            from provisioningserver.path import get_data_path
            from provisioningserver.rackdservices import tftp_offload
            from twisted.internet.endpoints import UNIXServerEndpoint
            tftp_offload_socket = get_data_path(
                "/var/lib/maas/tftp-offload.sock")
            tftp_offload_endpoint = UNIXServerEndpoint(
                reactor, tftp_offload_socket, wantPID=False)
            tftp_offload_service = tftp_offload.TFTPOffloadService(
                reactor, tftp_offload_endpoint, tftp_service.backend)
            tftp_offload_service.setName("tftp-offload")
            return tftp_offload_service
        # *** /EXPERIMENTAL ***

        return tftp_service

    def _makeImageDownloadService(self, rpc_service, tftp_root):
        from provisioningserver.rackdservices.image_download_service \
            import ImageDownloadService
        image_download_service = ImageDownloadService(
            rpc_service, tftp_root, reactor)
        image_download_service.setName("image_download")
        return image_download_service

    def _makeLeaseSocketService(self, rpc_service):
        from provisioningserver.rackdservices.lease_socket_service import (
            LeaseSocketService)
        lease_socket_service = LeaseSocketService(
            rpc_service, reactor)
        lease_socket_service.setName("lease_socket_service")
        return lease_socket_service

    def _makeNodePowerMonitorService(self):
        from provisioningserver.rackdservices.node_power_monitor_service \
            import NodePowerMonitorService
        node_monitor = NodePowerMonitorService(reactor)
        node_monitor.setName("node_monitor")
        return node_monitor

    def _makeRPCService(self):
        from provisioningserver.rpc.clusterservice import ClusterClientService
        rpc_service = ClusterClientService(reactor)
        rpc_service.setName("rpc")
        return rpc_service

    def _makeNetworksMonitoringService(self, rpc_service, clock=reactor):
        from provisioningserver.rackdservices.networks_monitoring_service \
            import RackNetworksMonitoringService
        networks_monitor = RackNetworksMonitoringService(rpc_service, clock)
        networks_monitor.setName("networks_monitor")
        return networks_monitor

    def _makeDHCPProbeService(self, rpc_service):
        from provisioningserver.rackdservices.dhcp_probe_service \
            import DHCPProbeService
        dhcp_probe_service = DHCPProbeService(
            rpc_service, reactor)
        dhcp_probe_service.setName("dhcp_probe")
        return dhcp_probe_service

    def _makeServiceMonitorService(self, rpc_service):
        from provisioningserver.rackdservices.service_monitor_service \
            import ServiceMonitorService
        service_monitor = ServiceMonitorService(rpc_service, reactor)
        service_monitor.setName("service_monitor")
        return service_monitor

    def _makeNetworkTimeProtocolService(self, rpc_service):
        from provisioningserver.rackdservices import ntp
        ntp_service = ntp.RackNetworkTimeProtocolService(rpc_service, reactor)
        ntp_service.setName("ntp")
        return ntp_service

    def _makeServices(self, tftp_root, tftp_port, clock=reactor):
        # Several services need to make use of the RPC service.
        rpc_service = self._makeRPCService()
        yield rpc_service
        # Other services that make up the MAAS Region Controller.
        yield self._makeNetworksMonitoringService(rpc_service, clock=clock)
        yield self._makeDHCPProbeService(rpc_service)
        yield self._makeLeaseSocketService(rpc_service)
        yield self._makeNodePowerMonitorService()
        yield self._makeServiceMonitorService(rpc_service)
        yield self._makeImageDownloadService(rpc_service, tftp_root)
        yield self._makeNetworkTimeProtocolService(rpc_service)
        # The following are network-accessible services.
        yield self._makeImageService(tftp_root)
        yield self._makeTFTPService(tftp_root, tftp_port, rpc_service)

    def _configureCrochet(self):
        # Prevent other libraries from starting the reactor via crochet.
        # In other words, this makes crochet.setup() a no-op.
        import crochet
        crochet.no_setup()

    def _configureLogging(self, verbosity: int):
        # Get something going with the logs.
        logger.configure(verbosity, logger.LoggingMode.TWISTD)

    def makeService(self, options, clock=reactor):
        """Construct the MAAS Cluster service."""
        register_sigusr2_thread_dump_handler()
        add_patches_to_txtftp()
        add_patches_to_twisted()

        self._configureCrochet()
        self._configureLogging(options["verbosity"])

        with ClusterConfiguration.open() as config:
            tftp_root = config.tftp_root
            tftp_port = config.tftp_port

        from provisioningserver import services
        for service in self._makeServices(tftp_root, tftp_port, clock=clock):
            service.setServiceParent(services)

        return services
