# Copyright 2016-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Monkey patch for the MAAS region server, with code for region server patching.
"""

__all__ = [
    "add_patches",
]

import inspect
import re

from provisioningserver.monkey import add_patches_to_twisted


fixed_re = re.compile(r"^([a-z0-9.-]+|\[[a-f0-9]*:[a-f0-9:\.]+\])(:\d+)?$")


def fix_django_http_request():
    """Add support for ipv6-formatted ipv4 addresses to django requests.

       See https://bugs.launchpad.net/ubuntu/+source/python-django/+bug/1611923
    """
    import django.http.request
    if not django.http.request.host_validation_re.match("[::ffff:127.0.0.1]"):
        django.http.request.host_validation_re = fixed_re


def fix_piston_emitter_related():
    """Fix Piston so it uses cached data for the `_related`.

    Piston emitter code is all one large function. Instead of including that
    large chunk of code in MAAS to fix this one issue we modify the source of
    the function and re-evaluate it.

    The `_related` function uses `iterator` which skips precached relations,
    changing it to `all` provides the same behaviour while using the precached
    data.
    """
    from piston3 import emitters
    bad_line = 'return [ _model(m, fields) for m in data.iterator() ]'
    new_line = 'return [ _model(m, fields) for m in data.all() ]'
    try:
        source = inspect.getsource(emitters.Emitter.construct)
    except OSError:
        # Fails with 'could not get source code' if its already patched. So we
        # allow this error to occur.
        pass
    else:
        if source.find(bad_line) > 0:
            source = source.replace(bad_line, new_line, 1)
            func_body = [
                line[4:]
                for line in source.splitlines()[1:]
            ]
            new_source = ['def emitter_new_construct(self):'] + func_body
            new_source = '\n'.join(new_source)
            local_vars = {}
            exec(new_source, emitters.__dict__, local_vars)
            emitters.Emitter.construct = local_vars['emitter_new_construct']


def fix_piston_consumer_delete():
    """Fix Piston so it doesn't try to send an email when a user is delete."""
    from piston3 import signals
    signals.send_consumer_mail = lambda consumer: None


def add_patches():
    add_patches_to_twisted()
    fix_django_http_request()
    fix_piston_emitter_related()
    fix_piston_consumer_delete()
    # yxp add need test
    fix_django_big_auto_field()



# fix django version problem
# author:yxp

def fix_django_big_auto_field():
    from django.db import models as django_models
    # from django.db import connection

    class BigAutoField(django_models.AutoField):
        description = _("Big (8 byte) integer")

        def get_internal_type(self):
            return "BigAutoField"

        def rel_db_type(self, connection):
            return django_models.BigIntegerField().db_type(connection=connection)
    setattr(django_models, "BigAutoField", BigAutoField)