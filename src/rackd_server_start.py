#!/usr/bin/env python3
# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

#from provisioningserver.server import run
#from maasserver.server import run
import pdb
import os


def main():
    # from provisioningserver.__main__ import main
    # main()
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE", "maasserver.djangosettings.settings")
    from maasserver.server import run
    run()

if __name__ == "__main__":
    main()
