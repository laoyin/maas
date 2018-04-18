#!/usr/bin/env python3
# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# from provisioningserver.server import run
from maasserver.server import run
import pdb
import os
from maasserver.monkey import fix_django_big_auto_field


def main():
    # from provisioningserver.__main__ import main
    # main()
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE", "maasserver.djangosettings.settings")
    os.environ.setdefault(
        "/snap/bin/rackd_server_start.py", "/home/pan/qinyun/maas/src/rackd_server_start.py")
    from maasserver.server import run
    # fix django version problem
    fix_django_big_auto_field()
    run()

if __name__ == "__main__":
    run()

