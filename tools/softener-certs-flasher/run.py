from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

    from softener_certs_flasher.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
