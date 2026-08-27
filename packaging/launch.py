"""pyinstaller entry point. keeps the spec pointed at one stable file."""

import sys

from reelpipe.app.main import main

sys.exit(main())
