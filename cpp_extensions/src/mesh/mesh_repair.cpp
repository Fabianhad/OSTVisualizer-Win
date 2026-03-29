#include "mesh_repair.hpp"
#include <unordered_map>
#include <unordered_set>
#include <cmath>
#include <algorithm>
namespace ost_geometry
{
    namespace
    {
        struct VertexHash
        {
            double tolerance;
            VertexHash(double tol = 1e-10) : tolerance(tol) {}
            size_t operator()(const std::array<double, 3> &v) const
            {
                auto quantize = [this](double x) -> int64_t
                {
                    return static_cast<int64_t>(std::round(x / tolerance));
                };
                size_t h1 = std::hash<int64_t>{}(quantize(v[0]));
                size_t h2 = std::hash<int64_t>{}(quantize(v[1]));
                size_t h3 = std::hash<int64_t>{}(quantize(v[2]));
                return h1 ^ (h2 << 1) ^ (h3 << 2);
            }
        };
        struct VertexEqual
        {
            double tolerance;
            VertexEqual(double tol = 1e-10) : tolerance(tol) {}
            bool operator()(const std::array<double, 3> &a, const std::array<double, 3> &b) const
            {
                return std::abs(a[0] - b[0]) < tolerance &&
                       std::abs(a[1] - b[1]) < tolerance &&
                       std::abs(a[2] - b[2]) < tolerance;
            }
        };
        std::array<double, 3> compute_face_normal(
            const std::array<double, 3> &v0,
            const std::array<double, 3> &v1,
            const std::array<double, 3> &v2)
        {
            std::array<double, 3> e1 = {v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]};
            std::array<double, 3> e2 = {v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]};
            std::array<double, 3> normal = {
                e1[1] * e2[2] - e1[2] * e2[1],
                e1[2] * e2[0] - e1[0] * e2[2],
                e1[0] * e2[1] - e1[1] * e2[0]};
            return normal;
        }
        double compute_face_area_2x(
            const std::array<double, 3> &v0,
            const std::array<double, 3> &v1,
            const std::array<double, 3> &v2)
        {
            auto normal = compute_face_normal(v0, v1, v2);
            return std::sqrt(normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2]);
        }
        struct Edge
        {
            uint32_t v0, v1;
            Edge(uint32_t a, uint32_t b)
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
            bool operator==(const Edge &other) const
            {
                return v0 == other.v0 && v1 == other.v1;
            }
        };
        struct EdgeHash
        {
            size_t operator()(const Edge &e) const
            {
                return std::hash<uint64_t>{}(
                    (static_cast<uint64_t>(e.v0) << 32) | e.v1);
            }
        };
    }
    bool remove_degenerate_faces(CppMeshData &mesh)
    {
        if (mesh.faces.empty())
        {
            return false;
        }
        std::vector<std::array<uint32_t, 3>> valid_faces;
        valid_faces.reserve(mesh.faces.size());
        constexpr double AREA_THRESHOLD = 1e-14;
        for (const auto &face : mesh.faces)
        {
            if (face[0] == face[1] || face[1] == face[2] || face[0] == face[2])
            {
                continue;
            }
            if (face[0] >= mesh.vertices.size() ||
                face[1] >= mesh.vertices.size() ||
                face[2] >= mesh.vertices.size())
            {
                continue;
            }
            double area = compute_face_area_2x(
                mesh.vertices[face[0]],
                mesh.vertices[face[1]],
                mesh.vertices[face[2]]);
            if (area > AREA_THRESHOLD)
            {
                valid_faces.push_back(face);
            }
        }
        if (valid_faces.size() != mesh.faces.size())
        {
            mesh.faces = std::move(valid_faces);
            return true;
        }
        return false;
    }
    bool merge_vertices(CppMeshData &mesh, double tolerance)
    {
        if (mesh.vertices.empty())
        {
            return false;
        }
        VertexHash hasher(tolerance);
        VertexEqual equal(tolerance);
        std::unordered_map<std::array<double, 3>, uint32_t, VertexHash, VertexEqual>
            vertex_map(mesh.vertices.size(), hasher, equal);
        std::vector<std::array<double, 3>> unique_vertices;
        std::vector<uint32_t> remap(mesh.vertices.size());
        unique_vertices.reserve(mesh.vertices.size());
        for (size_t i = 0; i < mesh.vertices.size(); ++i)
        {
            const auto &v = mesh.vertices[i];
            auto it = vertex_map.find(v);
            if (it == vertex_map.end())
            {
                uint32_t new_idx = static_cast<uint32_t>(unique_vertices.size());
                vertex_map[v] = new_idx;
                remap[i] = new_idx;
                unique_vertices.push_back(v);
            }
            else
            {
                remap[i] = it->second;
            }
        }
        if (unique_vertices.size() == mesh.vertices.size())
        {
            return false;
        }
        mesh.vertices = std::move(unique_vertices);
        for (auto &face : mesh.faces)
        {
            face[0] = remap[face[0]];
            face[1] = remap[face[1]];
            face[2] = remap[face[2]];
        }
        for (auto &edge : mesh.edges)
        {
            edge[0] = remap[edge[0]];
            edge[1] = remap[edge[1]];
        }
        return true;
    }
    bool remove_unreferenced_vertices(CppMeshData &mesh)
    {
        if (mesh.vertices.empty() || mesh.faces.empty())
        {
            return false;
        }
        std::vector<bool> referenced(mesh.vertices.size(), false);
        for (const auto &face : mesh.faces)
        {
            referenced[face[0]] = true;
            referenced[face[1]] = true;
            referenced[face[2]] = true;
        }
        for (const auto &edge : mesh.edges)
        {
            referenced[edge[0]] = true;
            referenced[edge[1]] = true;
        }
        size_t unreferenced_count = std::count(referenced.begin(), referenced.end(), false);
        if (unreferenced_count == 0)
        {
            return false;
        }
        std::vector<uint32_t> remap(mesh.vertices.size());
        std::vector<std::array<double, 3>> new_vertices;
        new_vertices.reserve(mesh.vertices.size() - unreferenced_count);
        for (size_t i = 0; i < mesh.vertices.size(); ++i)
        {
            if (referenced[i])
            {
                remap[i] = static_cast<uint32_t>(new_vertices.size());
                new_vertices.push_back(mesh.vertices[i]);
            }
        }
        mesh.vertices = std::move(new_vertices);
        for (auto &face : mesh.faces)
        {
            face[0] = remap[face[0]];
            face[1] = remap[face[1]];
            face[2] = remap[face[2]];
        }
        for (auto &edge : mesh.edges)
        {
            edge[0] = remap[edge[0]];
            edge[1] = remap[edge[1]];
        }
        return true;
    }
    bool repair_mesh(CppMeshData &mesh)
    {
        bool modified = false;
        modified |= merge_vertices(mesh);
        modified |= remove_degenerate_faces(mesh);
        modified |= remove_unreferenced_vertices(mesh);
        return modified;
    }
    bool is_watertight(const CppMeshData &mesh)
    {
        if (!mesh.is_valid())
        {
            return false;
        }
        std::unordered_map<Edge, int, EdgeHash> edge_count;
        for (const auto &face : mesh.faces)
        {
            edge_count[Edge(face[0], face[1])]++;
            edge_count[Edge(face[1], face[2])]++;
            edge_count[Edge(face[2], face[0])]++;
        }
        for (const auto &[edge, count] : edge_count)
        {
            if (count != 2)
            {
                return false;
            }
        }
        return true;
    }
    bool is_valid_for_boolean(const CppMeshData &mesh)
    {
        if (!mesh.is_valid())
        {
            return false;
        }
        if (mesh.faces.size() < 4)
        {
            return false;
        }
        for (const auto &face : mesh.faces)
        {
            if (face[0] >= mesh.vertices.size() ||
                face[1] >= mesh.vertices.size() ||
                face[2] >= mesh.vertices.size())
            {
                return false;
            }
        }
        return true;
    }
}
