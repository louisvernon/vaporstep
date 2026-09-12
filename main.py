from __future__ import annotations

import asyncio
import os

# Keep package import limited to web-safe modules. The finished desktop app
# continues to use vaporstep.app and its native camera/recording integrations.
os.environ["VAPORSTEP_WEB"] = "1"

import pygame  # noqa: F401  # make pygame explicit to pygbag's package scanner

from vaporstep.web_vaportap import main


asyncio.run(main())
