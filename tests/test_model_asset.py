from vaporstep.model_asset import load_pose_model_spec


def test_pose_model_manifest_is_version_pinned_and_hashed():
    spec = load_pose_model_spec()
    assert spec.version == "1"
    assert "/float16/1/" in spec.url
    assert "latest" not in spec.url
    assert spec.filename == "pose_landmarker_lite.task"
    assert spec.size_bytes == 5_777_746
    assert spec.sha256 == "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a"
    int(spec.sha256, 16)
