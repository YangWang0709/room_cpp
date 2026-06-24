# C++ Stable Pose 10-room Smoke Results

## Environment

- Commit: `bb7e75ef5a7ccb7c7fa1019ee455ddb3146eec8f`
- Python: `3.11.15`
- trimesh: `3.22.5`

## Configuration

- `INFINIGEN_DISABLE_NATURE_SHELF_CREATURE_TRINKETS=1`
- `INFINIGEN_STABLE_POSE_BACKEND=cpp`
- `INFINIGEN_VALIDATE_CPP_STABLE_POSE=1` for the canary run only
- `INFINIGEN_PROFILE_STABLE_POSE=1`
- `INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE` unset
- `INFINIGEN_DISABLE_CPP_STABLE_POSE` unset
- `compose_indoors.terrain_enabled=False`
- `home_room_constraints.has_fewer_rooms=False`
- `restrict_solving.solve_max_rooms=10`
- `populate_doors.door_chance=0`
- Seed: `0`
- Task: `coarse`

## Results

| Run | Result | MAIN TOTAL | Output |
| --- | --- | --- | --- |
| `cpp+canary` 10-room no-creature | Success | `3:17:12.376495` | `outputs/smoke_cpp_stable_pose_10room/cpp_canary_seed0_no_creature/coarse/scene.blend` |
| `cpp` no-canary 10-room no-creature | Success | `3:14:36.568228` | `outputs/smoke_cpp_stable_pose_10room/cpp_seed0_no_creature/coarse/scene.blend` |
| USDC export from no-canary run | Success | n/a | `outputs/smoke_cpp_stable_pose_10room/usdc_cpp_seed0_no_creature/export_scene.blend/export_scene.usdc` |

## Log Checks

- `cpp+canary` exact stable-pose failure scan found no matches for:
  `canary failed`, `StablePose`, `StablePoseValidationError`, `Validation`,
  `fallback`, `AttributeError`, `CarnivoreFactory`, or `HerbivoreFactory`.
- `cpp` no-canary exact stable-pose failure scan found no matches for:
  `canary failed`, `StablePose`, `StablePoseValidationError`, `Validation`,
  `fallback`, `AttributeError`, `CarnivoreFactory`, or `HerbivoreFactory`.
- Both 10-room runs had 24 solver constraint warnings matching
  `Solver has failed to satisfy constraints`; these are continuing solver
  warnings, not stable-pose validation failures.
- USDC export scan found no matches for `Error`, `Exception`, `Traceback`, or
  `failed`.

## Output Sizes

- `cpp+canary` output directory: `4.5G`
- `cpp` no-canary output directory: `4.6G`
- USDC export output directory: `7.3G`
- Exported USDC file: `4.9G`

## Conclusion

- The opt-in C++ stable pose backend passes 10-room no-creature smoke with
  canary validation enabled.
- The opt-in C++ stable pose backend passes 10-room no-creature smoke without
  canary validation.
- USDC export from the no-canary 10-room result succeeds.
- The creature lofting bug remains a separate task; this run used the opt-in
  no-creature filter and did not exercise `CarnivoreFactory` or
  `HerbivoreFactory`.
- Next steps can proceed to an Isaac visual check, a separate creature lofting
  fix, or further typed-loop optimization in the C++ stable pose core.
