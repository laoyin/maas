#!/bin/bash
# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

set -e

# Supervisord starts workers at 0 where as systemd starts them at 1. Increment
# the WORKER_ID by 1 to keep it consistent with systemd.
MAAS_REGIOND_WORKER_ID=$((MAAS_REGIOND_WORKER_ID+1))
export MAAS_REGIOND_WORKER_ID

# Configure python and django.
export DJANGO_SETTINGS_MODULE=maasserver.djangosettings.settings

# Configure MAAS to work in a snap.
export MAAS_PATH="$SNAP"
export MAAS_ROOT="$SNAP_DATA"
export MAAS_REGION_CONFIG="$SNAP_DATA/regiond.conf"
export MAAS_DNS_CONFIG_DIR="$SNAP_DATA/bind"
export MAAS_PROXY_CONFIG_DIR="$SNAP_DATA/proxy"
export MAAS_IMAGES_KEYRING_FILEPATH="/usr/share/keyrings/ubuntu-cloudimage-keyring.gpg"
export MAAS_THIRD_PARTY_DRIVER_SETTINGS="$SNAP/etc/maas/drivers.yaml"

# Run the regiond.
exec $SNAP/usr/bin/twistd3 --logger=provisioningserver.logger.EventLogger --nodaemon --pidfile= maas-regiond

