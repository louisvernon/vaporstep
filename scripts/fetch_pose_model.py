from __future__ import annotations

from pathlib import Path
import sys
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vaporstep.model_asset import load_pose_model_spec, verify_model


root = ROOT
spec = load_pose_model_spec()
out = root / "assets" / spec.filename
out.parent.mkdir(parents=True, exist_ok=True)

ok, reason = verify_model(out, spec)
if ok:
    print(f"{spec.name} v{spec.version} already present and verified: {out}")
else:
    if out.exists():
        print(f"Existing model is not the pinned artifact ({reason}); replacing it.")
        out.unlink()

    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)

    print(f"Downloading pinned {spec.name} v{spec.version}")
    print(spec.url)
    urlretrieve(spec.url, tmp)

    ok, reason = verify_model(tmp, spec)
    if not ok:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"Downloaded pose model failed verification: {reason}")

    tmp.replace(out)
    print(f"Verified SHA-256: {spec.sha256}")
    print(f"Installed: {out}")
