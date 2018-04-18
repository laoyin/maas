#!/usr/bin/env python3
# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os


def check_user():
    # At present, only root should execute this.
    if os.getuid() != 0:
        raise SystemExit("This utility may only be run as root.")


def run():

    # Run the main provisioning script.
    from provisioningserver.__main__ import main
    main()


if __name__ == "__main__":
    check_user()
    run()

