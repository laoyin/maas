#!/bin/bash
# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

set -e

# Get the current snap mode.
#SNAP_MODE=`cat $SNAP_COMMON/snap_mode`
SNAP_DATA = "/etc/maas"
SNAP_MODE = 'all'

if [ "$SNAP_MODE" = 'all' -a ! -e "$SNAP_DATA/rackd.conf" ]
then
    cat <<EOF >"$SNAP_DATA/rackd.conf"
maas_url: http://localhost:5240/MAAS
EOF
fi

# Remove the dhcp configuration so its not started unless needed.
rm -f "/var/lib/maas/dhcpd.sock"
rm -f "/var/lib/maas/dhcpd.conf"
rm -f "/var/lib/maas/dhcpd6.conf"

# Configure MAAS to work in a snap.
#export MAAS_PATH="$SNAP"
#export MAAS_ROOT="$SNAP_DATA"

export MAAS_PATH="/"
export MAAS_ROOT="/etc/maas/"
export MAAS_CLUSTER_CONFIG="$SNAP_DATA/rackd.conf"

# Setup language and perl5 correctly. Needed by tgt-admin written in
# Perl, yes really!
#
# XXX blake_r: Fix the hardcoded x86_64-linux-gnu to work for other
# architectures.
export LANGUAGE="C.UTF-8"
export LC_ALL="C.UTF-8"
export LANG="C.UTF-8"
export PERL5LIB="$SNAP/usr/lib/x86_64-linux-gnu/perl/5.22:$SNAP/usr/share/perl/5.22:$SNAP/usr/share/perl5"

# Run the rackd.
exec $SNAP/usr/bin/twistd3 --logger=provisioningserver.logger.EventLogger --nodaemon --pidfile= maas-rackd

