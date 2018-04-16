# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Patch django to work with twisted for MAAS."""

__all__ = [
    "patch_get_script_prefix",
]


def patch_get_script_prefix():
    """Patch internal django _prefixes to a global.

    Django sets up the _prefixes as a thread.local(). This causes an issue with
    twisted or any other thread, as it does not get the correct prefix when
    using reverse. This converts the local() into an object that is global.
    """
    try:
        from django.urls import base
        base._prefixes = type('', (), {})()
    except ImportError:
        from django.core import urlresolvers
        urlresolvers._prefixes = type('', (), {})()

    try:
        fix_django_big_auto_field()
    except Exception as e:
        print(str(e))

# fix django version problem
# author:yxp

def fix_django_big_auto_field():
    import django.db.models
    # from django.db import connection
    from django.utils.translation import ugettext_lazy as _
    class BigAutoField(django.db.models.AutoField):
        description = _("Big (8 byte) integer")
        def get_internal_type(self):
            return "BigAutoField"
        def rel_db_type(self, connection):
            return django.db.models.BigIntegerField().db_type(connection=connection)

    django.db.models.BigAutoField = BigAutoField