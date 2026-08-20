#pragma once
#include "mesh_data.hpp"
#include <vector>
namespace ost_geometry
{
    std::vector<std::array<uint32_t, 2>> extract_feature_edges(
        const CppMeshData &mesh,
        double angle_threshold = 0.1);
    double compute_dihedral_angle(
        const std::array<double, 3> &v0,
        const std::array<double, 3> &v1,
        const std::array<double, 3> &v2,
        const std::array<double, 3> &v3);
}
