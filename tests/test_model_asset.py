from vaporstep.model_asset import load_pose_model_spec


def test_pose_model_manifest_is_version_pinned_and_hashed():
    spec = load_pose_model_spec()
    assert spec.version == "1"
    assert "/float16/1/" in spec.url
    assert "latest" not in spec.url
    assert spec.filename == "pose_landmarker_full.task"
    assert spec.size_bytes == 9_398_198
    assert len(spec.sha256) == 64
    int(spec.sha256, 16)
