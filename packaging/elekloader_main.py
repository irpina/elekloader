# SPDX-License-Identifier: GPL-2.0-or-later
"""The apps' entry point (PyInstaller): the window, as python -m elekloader."""
import sys

from elekloader.gui import main

sys.exit(main())
