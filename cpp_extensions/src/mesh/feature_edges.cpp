#include "feature_edges.hpp"
#include <unordered_map>
#include <unordered_set>
#include <cmath>
#include <algorithm>
namespace ost_geometry
{
    namespace
    {
        struct DirectedEdge
        {
            uint32_t v0, v1;
            DirectedEdge(uint32_t a, uint32_t b) : v0(a), v1(b) {}
            bool operator==(const DirectedEdge &other) const
            {
                return v0 == other.v0 && v1 == other.v1;
            }
        };
        struct DirectedEdgeHash
        {
            size_t operator()(const DirectedEdge &e) const
            {
                return std::hash<uint64_t>{}(
                    (static_cast<uint64_t>(e.v0) << 32) | e.v1);
            }
        };
        struct UndirectedEdge
        {
            uint32_t v0, v1;
            UndirectedEdge(uint32_t a, uint32_t b)
            {
                if (a < b)
                {
                    v0 = a;
                    v1 = b;
                }
                else
                {
                    v0 = b;
                    v1 = a;
                }
            }
            bool operator==(const UndirectedEdge &other) const
            {
                return v0 == other.v0 && v1 == other.v1;
            }
        };
        struct UndirectedEdgeHash
        {
            size_t operator()(const UndirectedEdge &e) const
            {
                return std::hash<uint64_t>{}(
                    (static_cast<uint64_t>(e.v0) << 32) | e.v1);
            }
        };
        std::array<double, 3> cross(const std::array<double, 3> &a, const std::array<double, 3> &b)
        {
            return {
                a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0]};
        }
        double dot(const std::array<double, 3> &a, const std::array<double, 3> &b)
        {
            return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
        }
        std::array<double, 3> subtract(const std::array<double, 3> &a, const std::array<double, 3> &b)
        {
            return {a[0] - b[0], a[1] - b[1], a[2] - b[2]};
        }
        std::array<double, 3> normalize(const std::array<double, 3> &v)
        {
            double len = std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
            if (len < 1e-10)
            {
                return {0, 0, 0};
            }
            return {v[0] / len, v[1] / len, v[2] / len};
        }
        std::array<double, 3> face_normal(
            const std::array<double, 3> &v0,
            const std::array<double, 3> &v1,
            const std::array<double, 3> &v2)
        {
            auto e1 = subtract(v1, v0);
            auto e2 = subtract(v2, v0);
            return cross(e1, e2);
        }
    }
    double compute_dihedral_angle(
        const std::array<double, 3> &v0,
        const std::array<double, 3> &v1,
        const std::array<double, 3> &v2,
        const std::array<double, 3> &v3)
    {
        auto n1 = normalize(face_normal(v0, v1, v2));
        auto n2 = normalize(face_normal(v1, v0, v3));
        double n1_len = std::sqrt(dot(n1, n1));
        double n2_len = std::sqrt(dot(n2, n2));
        if (n1_len < 1e-10 || n2_len < 1e-10)
        {
            return 0.0;
        }
        double cos_angle = dot(n1, n2);
        cos_angle = std::max(-1.0, std::min(1.0, cos_angle));
        return std::acos(cos_angle);
    }
    std::vector<std::array<uint32_t, 2>> extract_feature_edges(
        const CppMeshData &mesh,
        double angle_threshold)
    {
        if (!mesh.is_valid())
        {
            return {};
        }
        std::unordered_map<DirectedEdge, uint32_t, DirectedEdgeHash> edge_to_face;
        for (uint32_t fi = 0; fi < mesh.faces.size(); ++fi)
        {
            const auto &face = mesh.faces[fi];
            edge_to_face[DirectedEdge(face[0], face[1])] = fi;
            edge_to_face[DirectedEdge(face[1], face[2])] = fi;
            edge_to_face[DirectedEdge(face[2], face[0])] = fi;
        }
        std::unordered_set<UndirectedEdge, UndirectedEdgeHash> feature_edge_set;
        for (const auto &[edge, face_idx] : edge_to_face)
        {
            auto reverse_it = edge_to_face.find(DirectedEdge(edge.v1, edge.v0));
            if (reverse_it == edge_to_face.end())
            {
                feature_edge_set.insert(UndirectedEdge(edge.v0, edge.v1));
            }
            else
            {
                uint32_t adj_face_idx = reverse_it->second;
                const auto &face1 = mesh.faces[face_idx];
                const auto &face2 = mesh.faces[adj_face_idx];
                uint32_t v2 = 0, v3 = 0;
                for (int i = 0; i < 3; ++i)
                {
                    if (face1[i] != edge.v0 && face1[i] != edge.v1)
                    {
                        v2 = face1[i];
                        break;
                    }
                }
                for (int i = 0; i < 3; ++i)
                {
                    if (face2[i] != edge.v0 && face2[i] != edge.v1)
                    {
                        v3 = face2[i];
                        break;
                    }
                }
                double angle = compute_dihedral_angle(
                    mesh.vertices[edge.v0],
                    mesh.vertices[edge.v1],
                    mesh.vertices[v2],
                    mesh.vertices[v3]);
                if (angle > angle_threshold)
                {
                    feature_edge_set.insert(UndirectedEdge(edge.v0, edge.v1));
                }
            }
        }
        std::vector<std::array<uint32_t, 2>> result;
        result.reserve(feature_edge_set.size());
        for (const auto &edge : feature_edge_set)
        {
            result.push_back({edge.v0, edge.v1});
        }
        return result;
    }
}
