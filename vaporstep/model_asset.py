from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlretrieve

from .resources import resource_path
from .user_paths import cache_dir


POSE_MODEL_KEY = "pose_landmarker_lite"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    filename: str
    variant: str
    version: str
    url: str
    size_bytes: int
    sha256: str
    upstream: str
    license: str


def load_pose_model_spec() -> ModelSpec:
    manifest_path = resource_path("assets/models.json")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))[POSE_MODEL_KEY]
    return ModelSpec(**data)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(path: Path, spec: ModelSpec) -> tuple[bool, str]:
    if not path.exists():
        return False, "file does not exist"
    size = path.stat().st_size
    if size != spec.size_bytes:
        return False, f"size mismatch: expected {spec.size_bytes}, got {size}"
    actual_sha256 = _sha256(path)
    if actual_sha256 != spec.sha256:
        return False, f"SHA-256 mismatch: expected {spec.sha256}, got {actual_sha256}"
    return True, "verified"


def _cache_dir() -> Path:
    return cache_dir()


def ensure_pose_model() -> Path:
    """Return the verified bundled model, or download the pinned artifact."""
    spec = load_pose_model_spec()

    bundled = resource_path(f"assets/{spec.filename}")
    ok, _ = verify_model(bundled, spec)
    if ok:
        return bundled

    model_cache_dir = _cache_dir()
    model_cache_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_cache_dir / spec.filename
    ok, _ = verify_model(model_path, spec)
    if ok:
        return model_path

    print(f"Downloading pinned {spec.name} v{spec.version}...")
    tmp = model_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    urlretrieve(spec.url, tmp)

    ok, reason = verify_model(tmp, spec)
    if not ok:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded pose model failed verification: {reason}")

    tmp.replace(model_path)
    print(f"Pose model cached at {model_path}")
    return model_path
