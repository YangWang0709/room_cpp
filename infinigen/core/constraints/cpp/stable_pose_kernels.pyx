def backend_name():
    return "stable_pose_kernels_cpp"


def sanity_check():
    return True


def compute_stable_poses_from_arrays(
    double[:, ::1] vertices,
    double[:, :, ::1] triangles,
    double[:, ::1] face_normals,
    double[:, ::1] triangles_center,
    long[:, ::1] face_adjacency,
    long[:, ::1] face_adjacency_edges,
    double[:, ::1] sample_coms,
    double threshold,
):
    raise NotImplementedError("C++ stable pose core is not implemented yet")
