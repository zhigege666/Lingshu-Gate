"""Frozen application entry point."""

import sys


if __name__ == "__main__":
    if sys.argv[1:2] == ["native-update"]:
        from gate_native_update import run

        run(sys.argv[2:])
    else:
        from lingshu_gate.cli import main

        main()
