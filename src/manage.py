# def run():
#     # Force the production MAAS Django configuration.
#     os.environ.setdefault(
#         "DJANGO_SETTINGS_MODULE", "maasserver.djangosettings.settings")
#
#     # Let Django do the rest.
#     from django.core import management
#     management.execute_from_command_line()

#!/usr/bin/env python3
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "maasserver.djangosettings.settings")

    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)