#!/bin/sh

set -e

edit_named_options() {
    # Remove any existing MAAS-related include line from
    # /etc/bind/named.conf.local, then re-add it.
    sed -i '/^include\s.*maas/d' /etc/bind/named.conf.local
    python3 manage.py get_named_conf --edit --config_path /etc/bind/named.conf.local

    # Add a line in /etc/bind/named.conf.options that includes the
    # /etc/named/maas/named.conf.options.inside.maas file.
    python3 manage.py edit_named_options --config-path /etc/bind/named.conf.options
}

fix_dns_permissions() {
    if [ -d /etc/bind/maas ]; then
        chown maas:root /etc/bind/maas
        chown -R maas:maas /etc/bind/maas/*
    fi
    if [ -f /etc/bind/maas/named.conf.maas ]; then
        chown maas:maas /etc/bind/maas/named.conf.maas
        chmod 644 /etc/bind/maas/named.conf.maas
    fi
    if [ -f /etc/bind/maas/named.conf.options.inside.maas ]; then
        chown maas:maas /etc/bind/maas/named.conf.options.inside.maas
        chmod 644 /etc/bind/maas/named.conf.options.inside.maas
    fi
    if [ -f /etc/bind/maas/rndc.conf.maas ]; then
        chown maas:root /etc/bind/maas/rndc.conf.maas
        chmod 600 /etc/bind/maas/rndc.conf.maas
    fi
    if [ -f /etc/bind/maas/named.conf.rndc.maas ]; then
        chown maas:bind /etc/bind/maas/named.conf.rndc.maas
        chmod 640 /etc/bind/maas/named.conf.rndc.maas
    fi
}

# This handles installs and re-configuration
if ([ "$1" = "configure" ] && [ -z "$2" ]) || [ -n "$DEBCONF_RECONFIGURE" ]; then
    # If /etc/bind/maas is empty, set_up_dns.
    if [ ! "$(ls -A /etc/bind/maas)" ]; then
        python3 manage.py set_up_dns
    fi

    # Fix permissions.
    fix_dns_permissions

    edit_named_options

elif [ "$1" = "configure" ]; then
    # Fix permissions
    fix_dns_permissions

    # ensure that DNS config is included
    edit_named_options
fi

invoke-rc.d bind9 restart || true

#DEBHELPER#
