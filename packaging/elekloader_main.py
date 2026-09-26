"""The Windows app's entry point (PyInstaller): the window, as python -m elekloader."""
import sys

from elekloader.gui import main

sys.exit(main())
