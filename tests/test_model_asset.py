from vaporstep.model_asset import (
    load_pose_model_spec,
    normalize_pose_model_mode,
)


def test_speed_pose_model_manifest_is_version_pinned_and_hashed():
    spec = load_pose_model_spec("speed")
    assert spec.version == "1"
    assert "/float16/1/" in spec.url
    assert "latest" not in spec.url
    assert spec.filename == "pose_landmarker_lite.task"
    assert spec.size_bytes == 5_777_746
    assert spec.sha256 == "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a"
    int(spec.sha256, 16)


def test_accuracy_pose_model_manifest_is_version_pinned_and_hashed():
    spec = load_pose_model_spec("accuracy")
    assert spec.version == "1"
    assert "/float16/1/" in spec.url
    assert "latest" not in spec.url
    assert spec.filename == "pose_landmarker_full.task"
    assert spec.size_bytes == 9_398_198
    assert spec.sha256 == "5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1"
    int(spec.sha256, 16)


def test_pose_model_mode_aliases_and_default():
    assert normalize_pose_model_mode("lite") == "speed"
    assert normalize_pose_model_mode("full") == "accuracy"
    assert normalize_pose_model_mode("unknown") == "speed"
    assert load_pose_model_spec().filename == "pose_landmarker_lite.task"
