"""Allows running: python -m devops_agent <command>."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
