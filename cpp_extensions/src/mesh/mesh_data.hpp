#pragma once
#include <vector>
#include <array>
#include <cstdint>
#include <limits>
#include <algorithm>
namespace ost_geometry
{
    struct CppMeshData
    {
        std::vector<std::array<double, 3>> vertices;
        std::vector<std::array<uint32_t, 3>> faces;
        std::vector<std::array<uint32_t, 2>> edges;
        bool is_valid() const
        {
            return !vertices.empty() && !faces.empty();
        }
        void clear()
        {
            vertices.clear();
            faces.clear();
            edges.clear();
        }
        void reserve(size_t vertex_count, size_t face_count, size_t edge_count = 0)
        {
            vertices.reserve(vertex_count);
            faces.reserve(face_count);
            if (edge_count > 0)
            {
                edges.reserve(edge_count);
            }
        }
        struct AABB
        {
            std::array<double, 3> min_bounds;
            std::array<double, 3> max_bounds;
            bool intersects(const AABB &other) const
            {
                return !(max_bounds[0] < other.min_bounds[0] ||
                         min_bounds[0] > other.max_bounds[0] ||
                         max_bounds[1] < other.min_bounds[1] ||
                         min_bounds[1] > other.max_bounds[1] ||
                         max_bounds[2] < other.min_bounds[2] ||
                         min_bounds[2] > other.max_bounds[2]);
            }
        };
        AABB compute_aabb() const
        {
            AABB aabb;
            constexpr double max_val = std::numeric_limits<double>::max();
            constexpr double min_val = std::numeric_limits<double>::lowest();
            aabb.min_bounds = {max_val, max_val, max_val};
            aabb.max_bounds = {min_val, min_val, min_val};
            for (const auto &v : vertices)
            {
                for (int i = 0; i < 3; ++i)
                {
                    aabb.min_bounds[i] = std::min(aabb.min_bounds[i], v[i]);
                    aabb.max_bounds[i] = std::max(aabb.max_bounds[i], v[i]);
                }
            }
            return aabb;
        }
    };
}
