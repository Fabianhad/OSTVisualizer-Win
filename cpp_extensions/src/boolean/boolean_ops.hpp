#pragma once
#include "mesh_data.hpp"
#include <optional>
#include <vector>
namespace ost_geometry
{
    std::optional<CppMeshData> boolean_difference(
        const CppMeshData &positive,
        const CppMeshData &negative);
    std::optional<CppMeshData> boolean_difference_batch(
        const CppMeshData &positive,
        const std::vector<CppMeshData> &negatives);
    std::optional<CppMeshData> boolean_union(
        const CppMeshData &mesh1,
        const CppMeshData &mesh2);
    std::optional<CppMeshData> boolean_intersection(
        const CppMeshData &mesh1,
        const CppMeshData &mesh2);
    bool aabb_intersects(const CppMeshData &a, const CppMeshData &b);
}
