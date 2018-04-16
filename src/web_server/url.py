# Copyright 2012-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
根据maas源码，自定义api，满足特定需求

"""

__all__ = []
from maasserver.api.auth import api_auth
from django.conf.urls import url
from web_server.api.devices import (
    DeviceHandler,
    DevicesHandler,
)

from web_server.api.dhcpsnippets import (
    DHCPSnippetHandler,
    DHCPSnippetsHandler,
)
from web_server.api.discoveries import (
    DiscoveriesHandler,
    DiscoveryHandler,
)

from web_server.api.support import (
    AdminRestrictedResource,
    OperationsResource,
    RestrictedResource,
)

from web_server.api.test import (
    TestHandler
)



device_handler = RestrictedResource(DeviceHandler, authentication=api_auth)
devices_handler = RestrictedResource(DevicesHandler, authentication=api_auth)
dhcp_snippet_handler = RestrictedResource(
    DHCPSnippetHandler, authentication=api_auth)
dhcp_snippets_handler = RestrictedResource(
    DHCPSnippetsHandler, authentication=api_auth)
discovery_handler = RestrictedResource(
    DiscoveryHandler, authentication=api_auth)
discoveries_handler = RestrictedResource(
    DiscoveriesHandler, authentication=api_auth)

test_heandler = OperationsResource(TestHandler)

# API URLs accessible to anonymous users.
# urlpatterns = [
#     url(r'doc/$', api_doc, name='api-doc'),
#     url(r'describe/$', describe, name='describe'),
#     url(r'version/$', version_handler, name='version_handler'),
# ]


# API URLs for logged-in users.
urlpatterns = [
    url(
        r'^devices/(?P<system_id>[^/]+)/$', device_handler,
        name='device_handler'),
    url(r'^devices/$', devices_handler, name='devices_handler'),
    url(
        r'^dhcp-snippets/$',
        dhcp_snippets_handler, name='dhcp_snippets_handler'),
    url(
        r'^dhcp-snippets/(?P<id>[^/]+)/$',
        dhcp_snippet_handler, name='dhcp_snippet_handler'),
    url(r'^discovery/$', discoveries_handler, name='discoveries_handler'),
    url(
        r'^discovery/(?P<discovery_id>[.: \w=^]+)/*/$',
        discovery_handler, name='discovery_handler'),
]



# API urls for yxp test/

urlpatterns +=[
    url(r'^test/$', test_heandler, name='test'),

]

# API URLs for admin users.
# urlpatterns += [
#     url(
#         r'^commissioning-scripts/$', commissioning_scripts_handler,
#         name='commissioning_scripts_handler'),
#     url(
#         r'^commissioning-scripts/(?P<name>[^/]+)$',
#         commissioning_script_handler, name='commissioning_script_handler'),
#     url(
#         r'^license-keys/$', license_keys_handler, name='license_keys_handler'),
#     url(
#         r'^license-key/(?P<osystem>[^/]+)/(?P<distro_series>[^/]+)$',
#         license_key_handler, name='license_key_handler'),
#     url(r'^boot-sources/$',
#         boot_sources_handler, name='boot_sources_handler'),
#     url(r'^boot-sources/(?P<id>[^/]+)/$',
#         boot_source_handler, name='boot_source_handler'),
#     url(r'^boot-sources/(?P<boot_source_id>[^/]+)/selections/$',
#         boot_source_selections_handler,
#         name='boot_source_selections_handler'),
#     url(r'^boot-sources/(?P<boot_source_id>[^/]+)/selections/(?P<id>[^/]+)/$',
#         boot_source_selection_handler,
#         name='boot_source_selection_handler'),
# ]


# # Last resort: return an API 404 response.
# urlpatterns += [
#     url(r'^.*', not_found_handler, name='handler_404')
# ]
