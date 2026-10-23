"""Permite rodar com: python -m devops_agent <comando>."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
