# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Entrypoint for the maas rackd service."""

# Install the asyncio reactor with uvloop. This must be done before any other
# twisted code is imported.
import asyncio
import sys
import pdb

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


from twisted.python import usage
from twisted.scripts._twistd_unix import ServerOptions, UnixApplicationRunner


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

try:
    from maasserver.plugin import (
        RegionAllInOneServiceMaker,
        RegionMasterServiceMaker,
        RegionWorkerServiceMaker,
    )
except ImportError:
    pass
else:
    # Regiond services that twisted could spawn.
    twistd_plugins.append(
        RegionMasterServiceMaker(
            "maas-regiond-master",
            "The MAAS Region Controller master process."))
    twistd_plugins.append(
        RegionWorkerServiceMaker(
            "maas-regiond-worker",
            "The MAAS Region Controller worker process."))
    twistd_plugins.append(
        RegionAllInOneServiceMaker(
            "maas-regiond-all",
            "The MAAS Region Controller all-in-one process."))


class Options(ServerOptions):
    """Override the plugins path for the server options."""

    @staticmethod
    def _getPlugins(interface):
        return twistd_plugins


def runService(service):
    """Run the `service`."""
    config = Options()
    args = [
        '--logger=provisioningserver.logger.EventLogger',
        '--nodaemon', '--pidfile=',
        'service=maas-rackd'
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
    """Run the maas-rackd service."""
    import pdb
    pdb.set_trace()
    runService('maas-rackd')


if __name__ == "__main__":
    run()