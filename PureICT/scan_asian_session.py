#!/usr/bin/env python
"""
PureICT / scan_asian_session.py

Point d'entree heritage — redirige vers PureICT.cli.main().

Le code a ete refactore en modules dans PureICT/ :
  - models.py      : dataclasses (AsianLevels, PreviousAsianLevels, FvgInfo)
  - config.py      : constantes + helpers temps + calc_max_lots
  - scanner.py     : scan_symbol(), scan_all_symbols(), FVG detection
  - display.py     : display_results(), export_csv(), export_json()
  - live.py        : live_monitor()
  - cli.py         : main() + argparse

Usage :
  python PureICT/scan_asian_session.py [options]
  python -m PureICT.cli [options]
"""

import os
import sys

# Ajouter la racine du projet au path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PureICT.cli import main

if __name__ == "__main__":
    sys.exit(main())
