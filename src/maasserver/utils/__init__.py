# Copyright 2012-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Utilities."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    'absolute_reverse',
    'absolute_reverse_url',
    'build_absolute_uri',
    'find_nodegroup',
    'get_db_state',
    'get_local_cluster_UUID',
    'ignore_unused',
    'make_validation_error_message',
    'strip_domain',
    'synchronised',
    ]

from functools import wraps
from urllib import urlencode
from urlparse import (
    urljoin,
    urlparse,
)

from django.core.urlresolvers import reverse
from maasserver.config import RegionConfiguration
from maasserver.enum import NODEGROUPINTERFACE_MANAGEMENT
from maasserver.exceptions import NodeGroupMisconfiguration
from maasserver.utils.orm import get_one
from provisioningserver.config import (
    ClusterConfiguration,
    UUID_NOT_SET,
)
from provisioningserver.utils.text import make_bullet_list


def get_db_state(instance, field_name):
    """Get the persisted state of a given field for a given model instance.

    :param instance: The model instance to consider.
    :type instance: :class:`django.db.models.Model`
    :param field_name: The name of the field to return.
    :type field_name: unicode
    """
    obj = get_one(instance.__class__.objects.filter(pk=instance.pk))
    if obj is None:
        return None
    else:
        return getattr(obj, field_name)


def ignore_unused(*args):
    """Suppress warnings about unused variables.

    This function does nothing.  Use it whenever you have deliberately
    unused symbols: pass them to this function and lint checkers will no
    longer consider them unused.
    """


def absolute_reverse(view_name, query=None, base_url=None, *args, **kwargs):
    """Return the absolute URL (i.e. including the URL scheme specifier and
    the network location of the MAAS server).  Internally this method simply
    calls Django's 'reverse' method and prefixes the result of that call with
    the configured MAAS URL.

    Consult the 'maas-region-admin local_config_set --default-url' command for
    details on how to set the MAAS URL.

    :param view_name: Django's view function name/reference or URL pattern
        name for which to compute the absolute URL.
    :param query: Optional query argument which will be passed down to
        urllib.urlencode.  The result of that call will be appended to the
        resulting url.
    :param base_url: Optional url used as base.  If None is provided, then
        configured MAAS URL will be used.
    :param args: Positional arguments for Django's 'reverse' method.
    :param kwargs: Named arguments for Django's 'reverse' method.

    """
    if not base_url:
        with RegionConfiguration.open() as config:
            base_url = config.maas_url
    url = urljoin(base_url, reverse(view_name, *args, **kwargs))
    if query is not None:
        url += '?%s' % urlencode(query, doseq=True)
    return url


def absolute_url_reverse(view_name, query=None, *args, **kwargs):
    """Returns the absolute path (i.e. starting with '/') for the given view.

    This utility is meant to be used by methods that need to compute URLs but
    run outside of Django and thus don't have the 'script prefix' transparently
    added the the URL.

    :param view_name: Django's view function name/reference or URL pattern
        name for which to compute the absolute URL.
    :param query: Optional query argument which will be passed down to
        urllib.urlencode.  The result of that call will be appended to the
        resulting url.
    :param args: Positional arguments for Django's 'reverse' method.
    :param kwargs: Named arguments for Django's 'reverse' method.
    """
    with RegionConfiguration.open() as config:
        abs_path = urlparse(config.maas_url).path
    if not abs_path.endswith('/'):
        # Add trailing '/' to get urljoin to behave.
        abs_path = abs_path + '/'
    # Force prefix to be '' so that Django doesn't use the 'script prefix' (
    # which might be there or not depending on whether or not the thread local
    # variable has been initialized).
    reverse_link = reverse(view_name, prefix='', *args, **kwargs)
    if reverse_link.startswith('/'):
        # Drop the leading '/'.
        reverse_link = reverse_link[1:]
    url = urljoin(abs_path, reverse_link)
    if query is not None:
        url += '?%s' % urlencode(query, doseq=True)
    return url


def build_absolute_uri(request, path):
    """Return absolute URI corresponding to given absolute path.

    :param request: An http request to the API.  This is needed in order to
        figure out how the client is used to addressing
        the API on the network.
    :param path: The absolute http path to a given resource.
    :return: Full, absolute URI to the resource, taking its networking
        portion from `request` but the rest from `path`.
    """
    scheme = "https" if request.is_secure() else "http"
    return "%s://%s%s" % (scheme, request.get_host(), path)


def strip_domain(hostname):
    """Return `hostname` with the domain part removed."""
    return hostname.split('.', 1)[0]


def get_local_cluster_UUID():
    """Return the UUID of the local cluster (or None if it cannot be found)."""
    with ClusterConfiguration.open() as config:
        if config.cluster_uuid == UUID_NOT_SET:
            return None
        else:
            return config.cluster_uuid


def find_nodegroup(request):
    """Find the nodegroup whose subnet contains the requester's address.

    There may be multiple matching nodegroups, but this endeavours to choose
    the most appropriate.

    :raises `maasserver.exceptions.NodeGroupMisconfiguration`: When more than
        one nodegroup claims to manage the requester's network.
    """
    # Circular imports.
    from maasserver.models import NodeGroup
    ip_address = request.META['REMOTE_ADDR']
    if ip_address is None:
        return None

    # Fetch nodegroups with interfaces in the requester's network,
    # preferring those with managed networks first. The `NodeGroup`
    # objects returned are annotated with the `management` field of the
    # matching `NodeGroupInterface`. See https://docs.djangoproject.com
    # /en/dev/topics/db/sql/#adding-annotations for this curious feature
    # of Django's ORM.
    query = NodeGroup.objects.raw("""
        SELECT
            ng.*,
            ngi.management
        FROM maasserver_nodegroup AS ng
        JOIN maasserver_nodegroupinterface AS ngi ON ng.id = ngi.nodegroup_id
        WHERE
            inet %s BETWEEN
                (ngi.ip & ngi.subnet_mask) AND
                (ngi.ip | ~ngi.subnet_mask)
        ORDER BY ngi.management DESC, ng.id ASC
        """, [ip_address])
    nodegroups = list(query)
    if len(nodegroups) == 0:
        return None
    if len(nodegroups) == 1:
        return nodegroups[0]

    # There are multiple matching nodegroups. Only zero or one may
    # have a managed interface, otherwise it is a misconfiguration.
    unmanaged = NODEGROUPINTERFACE_MANAGEMENT.UNMANAGED
    nodegroups_with_managed_interfaces = {
        nodegroup.id for nodegroup in nodegroups
        if nodegroup.management != unmanaged
        }
    if len(nodegroups_with_managed_interfaces) > 1:
        raise NodeGroupMisconfiguration(
            "Multiple clusters on the same network; only "
            "one cluster may manage the network of which "
            "%s is a member." % ip_address)
    return nodegroups[0]


def synchronised(lock):
    """Decorator to synchronise a call against a given lock.

    Note: if the function being wrapped is a generator, the lock will
    *not* be held for the lifetime of the generator; to this decorator,
    it looks like the wrapped function has returned.
    """
    def synchronise(func):
        @wraps(func)
        def call_with_lock(*args, **kwargs):
            with lock:
                return func(*args, **kwargs)
        return call_with_lock
    return synchronise


def gen_validation_error_messages(error):
    """Return massaged messages from a :py:class:`ValidationError`."""
    message_dict = error.message_dict
    for field in sorted(message_dict):
        field_messages = message_dict[field]
        if field == "__all__":
            for field_message in field_messages:
                yield field_message
        else:
            for field_message in field_messages:
                yield "%s: %s" % (field, field_message)


def make_validation_error_message(error):
    """Return a massaged message from a :py:class:`ValidationError`.

    The message takes the form of a textual bullet-list.
    """
    return make_bullet_list(gen_validation_error_messages(error))