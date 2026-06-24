import numpy as np
from libc.math cimport acos, atan, isfinite, sqrt, tan


cdef double PI = 3.141592653589793238462643383279502884


def backend_name():
    return "stable_pose_kernels_cpp"


def sanity_check():
    return True


def _orient3dfast(plane, pd):
    pa, pb, pc = plane
    adx = pa[0] - pd[0]
    bdx = pb[0] - pd[0]
    cdx = pc[0] - pd[0]
    ady = pa[1] - pd[1]
    bdy = pb[1] - pd[1]
    cdy = pc[1] - pd[1]
    adz = pa[2] - pd[2]
    bdz = pb[2] - pd[2]
    cdz = pc[2] - pd[2]

    return (
        adx * (bdy * cdz - bdz * cdy)
        + bdx * (cdy * adz - cdz * ady)
        + cdx * (ady * bdz - adz * bdy)
    )


cdef inline double _clamp_unit(double value):
    if value < -1.0:
        return -1.0
    if value > 1.0:
        return 1.0
    return value


cdef inline double _compute_static_prob_from_vectors(
    double v0x,
    double v0y,
    double v0z,
    double v1x,
    double v1y,
    double v1z,
    double v2x,
    double v2y,
    double v2z,
):
    cdef double n0 = sqrt(v0x * v0x + v0y * v0y + v0z * v0z)
    cdef double n1 = sqrt(v1x * v1x + v1y * v1y + v1z * v1z)
    cdef double n2 = sqrt(v2x * v2x + v2y * v2y + v2z * v2z)
    cdef double a
    cdef double b
    cdef double c
    cdef double s
    cdef double s_value
    cdef double area_term
    cdef double prob

    if n0 == 0.0 or n1 == 0.0 or n2 == 0.0:
        return 0.0

    v0x /= n0
    v0y /= n0
    v0z /= n0
    v1x /= n1
    v1y /= n1
    v1z /= n1
    v2x /= n2
    v2y /= n2
    v2z /= n2

    a = acos(_clamp_unit(v0x * v1x + v0y * v1y + v0z * v1z))
    b = acos(_clamp_unit(v1x * v2x + v1y * v2y + v1z * v2z))
    c = acos(_clamp_unit(v2x * v0x + v2y * v0y + v2z * v0z))
    s = (a + b + c) / 2.0

    s_value = s
    area_term = (
        tan(s_value / 2.0)
        * tan((s_value - a) / 2.0)
        * tan((s_value - b) / 2.0)
        * tan((s_value - c) / 2.0)
    )
    if isfinite(area_term) and area_term >= 0.0:
        prob = 1.0 / PI * atan(sqrt(area_term))
        if isfinite(prob):
            return prob

    s_value = s + 1e-8
    area_term = (
        tan(s_value / 2.0)
        * tan((s_value - a) / 2.0)
        * tan((s_value - b) / 2.0)
        * tan((s_value - c) / 2.0)
    )
    if isfinite(area_term) and area_term >= 0.0:
        prob = 1.0 / PI * atan(sqrt(area_term))
        if isfinite(prob):
            return prob

    return 0.0


def _compute_static_prob(tri, com):
    tri_arr = np.asarray(tri, dtype=np.float64)
    com_arr = np.asarray(com, dtype=np.float64)
    if tri_arr.shape != (3, 3) or com_arr.shape != (3,):
        raise ValueError("tri must have shape (3, 3) and com must have shape (3,)")

    return float(
        _compute_static_prob_from_vectors(
            tri_arr[0, 0] - com_arr[0],
            tri_arr[0, 1] - com_arr[1],
            tri_arr[0, 2] - com_arr[2],
            tri_arr[1, 0] - com_arr[0],
            tri_arr[1, 1] - com_arr[1],
            tri_arr[1, 2] - com_arr[2],
            tri_arr[2, 0] - com_arr[0],
            tri_arr[2, 1] - com_arr[1],
            tri_arr[2, 2] - com_arr[2],
        )
    )


cdef inline double _compute_static_prob_face(
    double[:, :, ::1] triangles,
    double[:, ::1] sample_coms,
    Py_ssize_t face_i,
    Py_ssize_t sample_i,
):
    return _compute_static_prob_from_vectors(
        triangles[face_i, 0, 0] - sample_coms[sample_i, 0],
        triangles[face_i, 0, 1] - sample_coms[sample_i, 1],
        triangles[face_i, 0, 2] - sample_coms[sample_i, 2],
        triangles[face_i, 1, 0] - sample_coms[sample_i, 0],
        triangles[face_i, 1, 1] - sample_coms[sample_i, 1],
        triangles[face_i, 1, 2] - sample_coms[sample_i, 2],
        triangles[face_i, 2, 0] - sample_coms[sample_i, 0],
        triangles[face_i, 2, 1] - sample_coms[sample_i, 1],
        triangles[face_i, 2, 2] - sample_coms[sample_i, 2],
    )


def _points_to_barycentric(triangles, points):
    edge_vectors = triangles[:, 1:] - triangles[:, :1]
    w = points - triangles[:, 0].reshape((-1, 3))

    dot00 = np.einsum("ij,ij->i", edge_vectors[:, 0], edge_vectors[:, 0])
    dot01 = np.einsum("ij,ij->i", edge_vectors[:, 0], edge_vectors[:, 1])
    dot02 = np.einsum("ij,ij->i", edge_vectors[:, 0], w)
    dot11 = np.einsum("ij,ij->i", edge_vectors[:, 1], edge_vectors[:, 1])
    dot12 = np.einsum("ij,ij->i", edge_vectors[:, 1], w)

    inverse_denominator = 1.0 / (dot00 * dot11 - dot01 * dot01)
    barycentric = np.zeros((len(triangles), 3), dtype=np.float64)
    barycentric[:, 2] = (dot00 * dot12 - dot01 * dot02) * inverse_denominator
    barycentric[:, 1] = (dot11 * dot02 - dot01 * dot12) * inverse_denominator
    barycentric[:, 0] = 1.0 - barycentric[:, 1] - barycentric[:, 2]
    return barycentric


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
    cdef Py_ssize_t sample_i
    cdef Py_ssize_t face_i
    cdef double[::1] probs_view

    vertices_arr = np.asarray(vertices, dtype=np.float64)
    triangles_arr = np.asarray(triangles, dtype=np.float64)
    face_normals_arr = np.asarray(face_normals, dtype=np.float64)
    triangles_center_arr = np.asarray(triangles_center, dtype=np.float64)
    face_adjacency_arr = np.asarray(face_adjacency)
    face_adjacency_edges_arr = np.asarray(face_adjacency_edges)
    sample_coms_arr = np.asarray(sample_coms, dtype=np.float64)

    num_faces = len(triangles_arr)
    num_samples = len(sample_coms_arr)
    if num_faces == 0 or num_samples == 0:
        return (
            np.empty((0, 4, 4), dtype=np.float64),
            np.empty((0,), dtype=np.float64),
        )

    neighbors = [[] for _ in range(num_faces)]
    for face_pair, edge in zip(face_adjacency_arr, face_adjacency_edges_arr):
        f0 = int(face_pair[0])
        f1 = int(face_pair[1])
        e0 = int(edge[0])
        e1 = int(edge[1])
        if 0 <= f0 < num_faces and 0 <= f1 < num_faces:
            neighbors[f0].append((f1, e0, e1))
            neighbors[f1].append((f0, e0, e1))

    norms_to_probs = {}
    inv_num_samples = 1.0 / float(num_samples)

    for sample_i in range(num_samples):
        sample_com = sample_coms_arr[sample_i]
        probs = np.empty(num_faces, dtype=np.float64)
        probs_view = probs
        for face_i in range(num_faces):
            probs_view[face_i] = _compute_static_prob_face(
                triangles, sample_coms, face_i, sample_i
            )

        proj_dists = np.einsum(
            "ij,ij->i",
            face_normals_arr,
            sample_com - triangles_arr[:, 0],
        )
        proj_coms = sample_com - np.einsum(
            "i,ij->ij",
            proj_dists,
            face_normals_arr,
        )
        barys = _points_to_barycentric(triangles_arr, proj_coms)
        unstable_face_indices = np.where(np.any(barys < 0, axis=1))[0]

        successors = np.full(num_faces, -1, dtype=np.int64)
        in_degree = np.zeros(num_faces, dtype=np.int64)

        for fi in unstable_face_indices:
            proj_com = proj_coms[fi]
            centroid = triangles_center_arr[fi]
            norm = face_normals_arr[fi]

            for tfi, e0, e1 in neighbors[int(fi)]:
                v1 = vertices_arr[e0]
                v2 = vertices_arr[e1]
                if np.dot(np.cross(v1 - centroid, v2 - centroid), norm) < 0:
                    v1, v2 = v2, v1

                plane1 = (centroid, v1, v1 + norm)
                plane2 = (centroid, v2 + norm, v2)
                if (
                    _orient3dfast(plane1, proj_com) >= 0
                    and _orient3dfast(plane2, proj_com) >= 0
                ):
                    successors[fi] = tfi
                    in_degree[tfi] += 1
                    break

        nodes = [i for i in range(num_faces) if in_degree[i] == 0]
        n_iters = 0
        while len(nodes) > 0 and n_iters <= num_faces:
            new_nodes = []
            for node in nodes:
                successor = int(successors[node])
                if successor < 0:
                    continue
                probs[successor] += probs[node]
                probs[node] = 0.0
                new_nodes.append(successor)
            nodes = new_nodes
            n_iters += 1

        for node in range(num_faces):
            prob = probs[node]
            if prob > 0.0:
                normal = face_normals_arr[node]
                key = tuple(np.around(normal, decimals=3))
                if key in norms_to_probs:
                    norms_to_probs[key]["prob"] += inv_num_samples * prob
                else:
                    norms_to_probs[key] = {
                        "prob": inv_num_samples * prob,
                        "normal": normal.copy(),
                    }

    transforms = []
    out_probs = []
    for value in norms_to_probs.values():
        prob = value["prob"]
        if prob <= threshold:
            continue

        tf = np.eye(4, dtype=np.float64)
        z = -1.0 * value["normal"]
        x = np.array([-z[1], z[0], 0.0], dtype=np.float64)
        x_norm = np.linalg.norm(x)
        if x_norm == 0.0:
            x = np.array([1.0, 0.0, 0.0], dtype=np.float64)
        else:
            x = x / x_norm
        y = np.cross(z, x)
        y = y / np.linalg.norm(y)
        tf[:3, :3] = np.array([x, y, z], dtype=np.float64)

        min_z = np.min(vertices_arr.dot(tf[2, :3]))
        tf[:3, 3] = np.array([0.0, 0.0, -min_z], dtype=np.float64)

        transforms.append(tf)
        out_probs.append(prob)

    if len(transforms) == 0:
        return (
            np.empty((0, 4, 4), dtype=np.float64),
            np.empty((0,), dtype=np.float64),
        )

    transforms = np.asarray(transforms, dtype=np.float64)
    out_probs = np.asarray(out_probs, dtype=np.float64)
    inds = np.argsort(-out_probs)
    return transforms[inds], out_probs[inds]
