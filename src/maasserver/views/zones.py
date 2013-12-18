# Copyright 2013 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Zones views."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    'ZoneAdd',
    'ZoneDelete',
    'ZoneEdit',
    'ZoneListView',
    'ZoneView',
    ]

from apiclient.utils import urlencode
from django.contrib import messages
from django.core.urlresolvers import reverse
from django.shortcuts import get_object_or_404
from django.views.generic import (
    CreateView,
    DetailView,
    UpdateView,
    )
from maasserver.forms import ZoneForm
from maasserver.models import Zone
from maasserver.views import (
    HelpfulDeleteView,
    PaginatedListView,
    )


class ZoneListView(PaginatedListView):

    context_object_name = "zone_list"

    def get_queryset(self):
        return Zone.objects.all().order_by('name')


class ZoneView(DetailView):
    """Mixin class used to fetch a zone by name."""

    context_object_name = 'zone'

    def get_object(self):
        zone_name = self.kwargs.get('name', None)
        return get_object_or_404(Zone, name=zone_name)

    def get_context_data(self, **kwargs):
        context = super(ZoneView, self).get_context_data(**kwargs)
        query_string = urlencode(
            [('query', 'zone=%s' % self.get_object().name)])
        context["node_list_link"] = (
            reverse('node-list') + "?" + query_string)
        return context


class ZoneAdd(CreateView):
    """View for creating an availability zone."""

    form_class = ZoneForm
    template_name = 'maasserver/zone_add.html'
    context_object_name = 'new_zone'

    def get_success_url(self):
        return reverse('zone-list')

    def form_valid(self, form):
        messages.info(self.request, "Zone added.")
        return super(ZoneAdd, self).form_valid(form)


class ZoneEdit(UpdateView):
    """View for editing an availability zone."""

    model = Zone
    template_name = 'maasserver/zone_edit.html'

    def get_object(self):
        zone_name = self.kwargs.get('name', None)
        return get_object_or_404(Zone, name=zone_name)

    def get_success_url(self):
        return reverse('zone-list')


class ZoneDelete(HelpfulDeleteView):
    """View for deleting an availability zone."""

    template_name = 'maasserver/zone_configm_delete.html'
    context_object_name = 'zone_to_delete'
    model = Zone

    def get_object(self):
        name = self.kwargs.get('name', None)
        return get_object_or_404(Zone, name=name)

    def get_next_url(self):
        return reverse('zone-list')

    def name_object(self, obj):
        """See `HelpfulDeleteView`."""
        return "Zone %s" % obj.name
