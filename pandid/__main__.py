"""Run the CLI as ``python -m pandid``.

This is the same entry point as the installed ``pandid`` command, for a checkout
or an environment whose scripts directory is not on PATH.
"""

import sys

from pandid.cli import main

if __name__ == "__main__":
    sys.exit(main())
