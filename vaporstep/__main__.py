import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from .player_visual_runtime import main

raise SystemExit(main())
