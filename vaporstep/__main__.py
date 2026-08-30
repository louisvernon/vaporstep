import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from .app import main

raise SystemExit(main())
