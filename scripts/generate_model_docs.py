from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vaporstep.model_asset import load_pose_model_specs


root = ROOT
sections = []
for spec in load_pose_model_specs():
    sections.append(
        f"""## {spec.name}

- Model variant: {spec.variant}
- Pinned upstream version: `{spec.version}`
- Filename: `{spec.filename}`
- Upstream URL: `{spec.url}`
- Expected size: `{spec.size_bytes:,}` bytes
- SHA-256: `{spec.sha256}`
- Upstream project: {spec.upstream}
- License: {spec.license}
"""
    )

text = """# Pinned model assets

This file is generated from `assets/models.json`. Edit the manifest, then run
`python scripts/generate_model_docs.py`.

""" + "\n".join(sections) + """
Both source-mode downloads and release builds use the same manifest and verify
the exact size and SHA-256 before accepting either model.
"""
(root / "MODEL_ASSETS.md").write_text(text, encoding="utf-8")
