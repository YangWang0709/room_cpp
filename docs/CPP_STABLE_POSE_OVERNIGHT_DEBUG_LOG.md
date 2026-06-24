# C++ Stable Pose Overnight Debug Log

## Issue 1: Static Probability Edge Case Test

- Phase: typed loop unit test.
- Symptom: the new `_compute_static_prob` reference test initially compared the
  center-of-mass-on-vertex case directly against
  `trimesh.poses._compute_static_prob`.
- Root cause: trimesh's private helper returns `nan` for that degenerate input,
  while the existing C++ backend intentionally returns `0.0` on zero-length
  vectors.
- Fix: keep the C++ behavior and assert exact `0.0` only when the trimesh
  reference is not finite.
- Verification: `pytest tests/test_stable_pose_wrapper.py
  tests/test_stable_pose_kernels.py tests/test_nature_shelf_trinkets_factory.py
  -q` passed with `32 passed, 3 warnings`.

## Issue 2: CSV Summary Helper Quoting

- Phase: documentation metric collection.
- Symptom: one ad-hoc `python -c` CSV summary command failed with a shell
  quoting `SyntaxError`; a second attempt used the wrong total-duration column
  and produced zero totals.
- Root cause: the timing CSV stores per-sample total time in
  `create_asset_total_duration`, not `duration`.
- Fix: reran the metric helper against `create_asset_total_duration` and used
  analyzer output as the cross-check.
- Verification: current reference total `140.230s`, optimized total `121.052s`,
  current reference stable-pose duration `77.186s`, optimized stable-pose
  duration `61.249s`.
