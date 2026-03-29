#include "boolean_ops.hpp"
#include "../earcut/earcut.hpp"
#include <manifold/manifold.h>
#include <stdexcept>
#include <cmath>
#include <cstring>
#include <algorithm>
#include <numeric>
#include <unordered_map>
#include <unordered_set>
#include <queue>
namespace ost_geometry
{
    namespace
    {
        constexpr double kSnapTol = 0.05;
        struct Vec3
        {
            double x, y, z;
            Vec3() noexcept : x(0), y(0), z(0) {}
            Vec3(double x_, double y_, double z_) noexcept : x(x_), y(y_), z(z_) {}
            explicit Vec3(const std::array<double, 3> &arr) noexcept : x(arr[0]), y(arr[1]), z(arr[2]) {}
            Vec3 operator-(const Vec3 &other) const noexcept
            {
                return Vec3(x - other.x, y - other.y, z - other.z);
            }
            Vec3 operator+(const Vec3 &other) const noexcept
            {
                return Vec3(x + other.x, y + other.y, z + other.z);
            }
            Vec3 operator*(double s) const noexcept
            {
                return Vec3(x * s, y * s, z * s);
            }
            double dot(const Vec3 &other) const noexcept
            {
                return x * other.x + y * other.y + z * other.z;
            }
            Vec3 cross(const Vec3 &other) const noexcept
            {
                return Vec3(
                    y * other.z - z * other.y,
                    z * other.x - x * other.z,
                    x * other.y - y * other.x);
            }
            double length() const noexcept
            {
                return std::sqrt(x * x + y * y + z * z);
            }
            Vec3 normalized() const noexcept
            {
                double len = length();
                if (len < 1e-12)
                    return Vec3(0, 0, 0);
                return Vec3(x / len, y / len, z / len);
            }
        };
        Vec3 compute_face_cross(const Vec3 &v0, const Vec3 &v1, const Vec3 &v2) noexcept
        {
            return (v1 - v0).cross(v2 - v0);
        }
        double compute_signed_volume(const CppMeshData &mesh) noexcept
        {
            double volume = 0.0;
            for (const auto &face : mesh.faces)
            {
                const auto &v0 = mesh.vertices[face[0]];
                const auto &v1 = mesh.vertices[face[1]];
                const auto &v2 = mesh.vertices[face[2]];
                volume += (v0[0] * (v1[1] * v2[2] - v2[1] * v1[2]) -
                           v1[0] * (v0[1] * v2[2] - v2[1] * v0[2]) +
                           v2[0] * (v0[1] * v1[2] - v1[1] * v0[2])) /
                          6.0;
            }
            return volume;
        }
        struct EdgeKey
        {
            uint32_t v0, v1;
            EdgeKey(uint32_t a, uint32_t b) noexcept
            {
                v0 = std::min(a, b);
                v1 = std::max(a, b);
            }
            bool operator==(const EdgeKey &other) const noexcept
            {
                return v0 == other.v0 && v1 == other.v1;
            }
        };
        struct EdgeKeyHash
        {
            size_t operator()(const EdgeKey &e) const noexcept
            {
                return std::hash<uint64_t>{}((static_cast<uint64_t>(e.v0) << 32) | e.v1);
            }
        };
        struct DirectedEdge
        {
            uint32_t from, to;
            DirectedEdge() noexcept : from(0), to(0) {}
            DirectedEdge(uint32_t f, uint32_t t) noexcept : from(f), to(t) {}
            bool operator==(const DirectedEdge &other) const noexcept
            {
                return from == other.from && to == other.to;
            }
        };
        struct DirectedEdgeHash
        {
            size_t operator()(const DirectedEdge &e) const noexcept
            {
                return std::hash<uint64_t>{}((static_cast<uint64_t>(e.from) << 32) | e.to);
            }
        };
        using EdgeFaceMap = std::unordered_map<EdgeKey, std::vector<size_t>, EdgeKeyHash>;
        EdgeFaceMap build_edge_face_map(const CppMeshData &mesh)
        {
            EdgeFaceMap edge_to_faces;
            for (size_t fi = 0; fi < mesh.faces.size(); ++fi)
            {
                const auto &f = mesh.faces[fi];
                edge_to_faces[EdgeKey(f[0], f[1])].push_back(fi);
                edge_to_faces[EdgeKey(f[1], f[2])].push_back(fi);
                edge_to_faces[EdgeKey(f[2], f[0])].push_back(fi);
            }
            return edge_to_faces;
        }
        void remap_mesh_indices(CppMeshData &mesh, const std::vector<uint32_t> &remap)
        {
            for (auto &face : mesh.faces)
            {
                face[0] = remap[face[0]];
                face[1] = remap[face[1]];
                face[2] = remap[face[2]];
            }
            std::vector<std::array<uint32_t, 2>> valid_edges;
            valid_edges.reserve(mesh.edges.size());
            for (auto &edge : mesh.edges)
            {
                uint32_t a = remap[edge[0]];
                uint32_t b = remap[edge[1]];
                if (a != b)
                    valid_edges.push_back({a, b});
            }
            mesh.edges = std::move(valid_edges);
        }
        void fix_face_winding(CppMeshData &mesh)
        {
            if (mesh.faces.empty())
                return;
            size_t num_faces = mesh.faces.size();
            auto edge_to_faces = build_edge_face_map(mesh);
            std::vector<bool> visited(num_faces, false);
            std::vector<bool> flipped(num_faces, false);
            for (size_t start_face = 0; start_face < num_faces; ++start_face)
            {
                if (visited[start_face])
                    continue;
                std::queue<size_t> queue;
                queue.push(start_face);
                visited[start_face] = true;
                while (!queue.empty())
                {
                    size_t fi = queue.front();
                    queue.pop();
                    const auto &face = mesh.faces[fi];
                    bool face_flipped = flipped[fi];
                    std::array<DirectedEdge, 3> edges;
                    if (!face_flipped)
                    {
                        edges = {
                            DirectedEdge(face[0], face[1]),
                            DirectedEdge(face[1], face[2]),
                            DirectedEdge(face[2], face[0])};
                    }
                    else
                    {
                        edges = {
                            DirectedEdge(face[0], face[2]),
                            DirectedEdge(face[2], face[1]),
                            DirectedEdge(face[1], face[0])};
                    }
                    for (const auto &edge : edges)
                    {
                        EdgeKey ek(edge.from, edge.to);
                        for (size_t adj_fi : edge_to_faces[ek])
                        {
                            if (adj_fi == fi || visited[adj_fi])
                                continue;
                            visited[adj_fi] = true;
                            const auto &adj_face = mesh.faces[adj_fi];
                            bool adj_same_direction = false;
                            for (int i = 0; i < 3; ++i)
                            {
                                uint32_t a = adj_face[i];
                                uint32_t b = adj_face[(i + 1) % 3];
                                if (a == edge.from && b == edge.to)
                                {
                                    adj_same_direction = true;
                                    break;
                                }
                            }
                            flipped[adj_fi] = adj_same_direction;
                            queue.push(adj_fi);
                        }
                    }
                }
            }
            for (size_t fi = 0; fi < num_faces; ++fi)
            {
                if (flipped[fi])
                {
                    std::swap(mesh.faces[fi][1], mesh.faces[fi][2]);
                }
            }
            if (compute_signed_volume(mesh) < 0)
            {
                for (auto &face : mesh.faces)
                {
                    std::swap(face[1], face[2]);
                }
            }
        }
        CppMeshData preprocess_mesh(CppMeshData mesh)
        {
            fix_face_winding(mesh);
            return mesh;
        }
        manifold::Manifold to_manifold(const CppMeshData &mesh)
        {
            if (!mesh.is_valid())
            {
                return manifold::Manifold();
            }
            CppMeshData preprocessed = preprocess_mesh(mesh);
            manifold::MeshGL meshgl;
            meshgl.vertProperties.reserve(preprocessed.vertices.size() * 3);
            for (const auto &v : preprocessed.vertices)
            {
                meshgl.vertProperties.push_back(static_cast<float>(v[0]));
                meshgl.vertProperties.push_back(static_cast<float>(v[1]));
                meshgl.vertProperties.push_back(static_cast<float>(v[2]));
            }
            meshgl.numProp = 3;
            meshgl.triVerts.reserve(preprocessed.faces.size() * 3);
            for (const auto &f : preprocessed.faces)
            {
                meshgl.triVerts.push_back(f[0]);
                meshgl.triVerts.push_back(f[1]);
                meshgl.triVerts.push_back(f[2]);
            }
            return manifold::Manifold(meshgl);
        }
        CppMeshData from_manifold(const manifold::Manifold &manifold_mesh)
        {
            CppMeshData result;
            if (manifold_mesh.IsEmpty())
            {
                return result;
            }
            manifold::MeshGL meshgl = manifold_mesh.GetMeshGL();
            if (meshgl.numProp < 3)
            {
                return result;
            }
            size_t num_verts = meshgl.vertProperties.size() / meshgl.numProp;
            result.vertices.reserve(num_verts);
            for (size_t i = 0; i < num_verts; ++i)
            {
                size_t idx = i * meshgl.numProp;
                result.vertices.push_back({static_cast<double>(meshgl.vertProperties[idx]),
                                           static_cast<double>(meshgl.vertProperties[idx + 1]),
                                           static_cast<double>(meshgl.vertProperties[idx + 2])});
            }
            size_t num_faces = meshgl.triVerts.size() / 3;
            result.faces.reserve(num_faces);
            for (size_t i = 0; i < num_faces; ++i)
            {
                size_t idx = i * 3;
                result.faces.push_back({meshgl.triVerts[idx],
                                        meshgl.triVerts[idx + 1],
                                        meshgl.triVerts[idx + 2]});
            }
            return result;
        }
        void snap_to_input_vertices(
            CppMeshData &result,
            const std::vector<std::array<float, 3>> &input_verts_f,
            double tolerance)
        {
            if (input_verts_f.empty() || result.vertices.empty())
                return;
            std::vector<size_t> sorted_idx(input_verts_f.size());
            std::iota(sorted_idx.begin(), sorted_idx.end(), size_t(0));
            std::sort(sorted_idx.begin(), sorted_idx.end(),
                      [&input_verts_f](size_t a, size_t b)
                      {
                          return input_verts_f[a][0] < input_verts_f[b][0];
                      });
            float tol_f = static_cast<float>(tolerance);
            for (auto &vert : result.vertices)
            {
                float vx = static_cast<float>(vert[0]);
                float vy = static_cast<float>(vert[1]);
                float vz = static_cast<float>(vert[2]);
                float x_lo = vx - tol_f;
                size_t lo = static_cast<size_t>(
                    std::lower_bound(sorted_idx.begin(), sorted_idx.end(), x_lo,
                                     [&input_verts_f](size_t idx, float val)
                                     { return input_verts_f[idx][0] < val; }) -
                    sorted_idx.begin());
                float best_dist2 = tol_f * tol_f;
                size_t best_idx = SIZE_MAX;
                for (size_t si = lo; si < sorted_idx.size(); ++si)
                {
                    size_t ii = sorted_idx[si];
                    float dx = input_verts_f[ii][0] - vx;
                    if (dx > tol_f)
                        break;
                    float dy = input_verts_f[ii][1] - vy;
                    float dz = input_verts_f[ii][2] - vz;
                    float d2 = dx * dx + dy * dy + dz * dz;
                    if (d2 < best_dist2)
                    {
                        best_dist2 = d2;
                        best_idx = ii;
                    }
                }
                if (best_idx != SIZE_MAX)
                {
                    vert[0] = static_cast<double>(input_verts_f[best_idx][0]);
                    vert[1] = static_cast<double>(input_verts_f[best_idx][1]);
                    vert[2] = static_cast<double>(input_verts_f[best_idx][2]);
                }
            }
            std::vector<uint32_t> remap(result.vertices.size());
            std::vector<std::array<double, 3>> unique_verts;
            unique_verts.reserve(result.vertices.size());
            auto hash_vert = [](const std::array<double, 3> &v) -> size_t
            {
                size_t h = 0;
                for (int i = 0; i < 3; ++i)
                {
                    uint64_t bits;
                    double val = v[i];
                    std::memcpy(&bits, &val, sizeof(bits));
                    h ^= std::hash<uint64_t>{}(bits) + 0x9e3779b9 + (h << 6) + (h >> 2);
                }
                return h;
            };
            std::unordered_map<size_t, std::vector<uint32_t>> hash_to_indices;
            for (size_t i = 0; i < result.vertices.size(); ++i)
            {
                size_t h = hash_vert(result.vertices[i]);
                bool found = false;
                auto map_it = hash_to_indices.find(h);
                if (map_it != hash_to_indices.end())
                {
                    for (uint32_t existing_idx : map_it->second)
                    {
                        const auto &ev = unique_verts[existing_idx];
                        if (ev[0] == result.vertices[i][0] &&
                            ev[1] == result.vertices[i][1] &&
                            ev[2] == result.vertices[i][2])
                        {
                            remap[i] = existing_idx;
                            found = true;
                            break;
                        }
                    }
                }
                if (!found)
                {
                    uint32_t new_idx = static_cast<uint32_t>(unique_verts.size());
                    remap[i] = new_idx;
                    unique_verts.push_back(result.vertices[i]);
                    hash_to_indices[h].push_back(new_idx);
                }
            }
            if (unique_verts.size() < result.vertices.size())
            {
                result.vertices = std::move(unique_verts);
                remap_mesh_indices(result, remap);
            }
        }
        void collapse_short_edges(CppMeshData &mesh, double threshold)
        {
            if (mesh.faces.empty())
                return;
            double thresh2 = threshold * threshold;
            size_t nv = mesh.vertices.size();
            std::vector<uint32_t> parent(nv);
            for (uint32_t i = 0; i < nv; ++i)
                parent[i] = i;
            auto find = [&](uint32_t x) -> uint32_t
            {
                while (parent[x] != x)
                {
                    parent[x] = parent[parent[x]];
                    x = parent[x];
                }
                return x;
            };
            auto unite = [&](uint32_t a, uint32_t b)
            {
                a = find(a);
                b = find(b);
                if (a != b)
                    parent[std::max(a, b)] = std::min(a, b);
            };
            for (const auto &face : mesh.faces)
            {
                uint32_t indices[3] = {face[0], face[1], face[2]};
                for (int e = 0; e < 3; ++e)
                {
                    uint32_t a = indices[e], b = indices[(e + 1) % 3];
                    const auto &va = mesh.vertices[a];
                    const auto &vb = mesh.vertices[b];
                    double dx = va[0] - vb[0];
                    double dy = va[1] - vb[1];
                    double dz = va[2] - vb[2];
                    if (dx * dx + dy * dy + dz * dz < thresh2)
                    {
                        unite(a, b);
                    }
                }
            }
            std::vector<uint32_t> remap(nv, UINT32_MAX);
            std::vector<std::array<double, 3>> new_verts;
            new_verts.reserve(nv);
            for (uint32_t i = 0; i < nv; ++i)
            {
                uint32_t root = find(i);
                if (remap[root] == UINT32_MAX)
                {
                    remap[root] = static_cast<uint32_t>(new_verts.size());
                    new_verts.push_back(mesh.vertices[root]);
                }
                remap[i] = remap[root];
            }
            if (new_verts.size() == nv)
                return;
            mesh.vertices = std::move(new_verts);
            std::vector<std::array<uint32_t, 3>> new_faces;
            new_faces.reserve(mesh.faces.size());
            for (auto &face : mesh.faces)
            {
                uint32_t a = remap[face[0]];
                uint32_t b = remap[face[1]];
                uint32_t c = remap[face[2]];
                if (a != b && b != c && a != c)
                {
                    new_faces.push_back({a, b, c});
                }
            }
            mesh.faces = std::move(new_faces);
            remap_mesh_indices(mesh, remap);
        }
        void retri_coplanar_patches(CppMeshData &mesh)
        {
            if (mesh.faces.size() < 2)
                return;
            const double NORMAL_TOL = 1e-6;
            const double PLANE_TOL = 0.01;
            size_t nf = mesh.faces.size();
            std::vector<Vec3> face_normals(nf);
            std::vector<double> face_d(nf);
            for (size_t i = 0; i < nf; ++i)
            {
                Vec3 v0(mesh.vertices[mesh.faces[i][0]]);
                Vec3 v1(mesh.vertices[mesh.faces[i][1]]);
                Vec3 v2(mesh.vertices[mesh.faces[i][2]]);
                Vec3 n = compute_face_cross(v0, v1, v2).normalized();
                face_normals[i] = n;
                face_d[i] = n.dot(v0);
            }
            auto edge_faces = build_edge_face_map(mesh);
            std::vector<int> group_id(nf, -1);
            std::vector<std::vector<size_t>> groups;
            for (size_t fi = 0; fi < nf; ++fi)
            {
                if (group_id[fi] >= 0)
                    continue;
                int gid = static_cast<int>(groups.size());
                groups.emplace_back();
                auto &group = groups.back();
                std::queue<size_t> bfs;
                bfs.push(fi);
                group_id[fi] = gid;
                group.push_back(fi);
                Vec3 ref_n = face_normals[fi];
                double ref_d = face_d[fi];
                if (ref_n.length() < 0.5)
                    continue;
                while (!bfs.empty())
                {
                    size_t cur = bfs.front();
                    bfs.pop();
                    const auto &f = mesh.faces[cur];
                    EdgeKey edges[3] = {
                        EdgeKey(f[0], f[1]),
                        EdgeKey(f[1], f[2]),
                        EdgeKey(f[2], f[0])};
                    for (const auto &ek : edges)
                    {
                        auto it = edge_faces.find(ek);
                        if (it == edge_faces.end())
                            continue;
                        for (size_t adj : it->second)
                        {
                            if (adj == cur || group_id[adj] >= 0)
                                continue;
                            Vec3 adj_n = face_normals[adj];
                            double cross_len = ref_n.cross(adj_n).length();
                            if (cross_len > NORMAL_TOL)
                                continue;
                            if (ref_n.dot(adj_n) < 0)
                                continue;
                            bool on_plane = true;
                            for (int vi = 0; vi < 3; ++vi)
                            {
                                Vec3 v(mesh.vertices[mesh.faces[adj][vi]]);
                                double dist = std::abs(ref_n.dot(v) - ref_d);
                                if (dist > PLANE_TOL)
                                {
                                    on_plane = false;
                                    break;
                                }
                            }
                            if (!on_plane)
                                continue;
                            group_id[adj] = gid;
                            group.push_back(adj);
                            bfs.push(adj);
                        }
                    }
                }
            }
            std::vector<bool> face_removed(nf, false);
            std::vector<std::array<uint32_t, 3>> new_faces_to_add;
            for (const auto &group : groups)
            {
                if (group.size() < 2)
                    continue;
                std::unordered_map<DirectedEdge, size_t, DirectedEdgeHash> half_edges;
                for (size_t fi : group)
                {
                    const auto &f = mesh.faces[fi];
                    half_edges[DirectedEdge(f[0], f[1])] = fi;
                    half_edges[DirectedEdge(f[1], f[2])] = fi;
                    half_edges[DirectedEdge(f[2], f[0])] = fi;
                }
                std::unordered_map<uint32_t, uint32_t> boundary_next;
                for (const auto &[he, _face_idx] : half_edges)
                {
                    DirectedEdge reverse(he.to, he.from);
                    if (half_edges.find(reverse) == half_edges.end())
                    {
                        if (boundary_next.count(he.from))
                        {
                            boundary_next.clear();
                            break;
                        }
                        boundary_next[he.from] = he.to;
                    }
                }
                if (boundary_next.empty())
                    continue;
                std::vector<std::vector<uint32_t>> loops;
                std::unordered_set<uint32_t> visited_boundary;
                size_t max_loop_size = mesh.vertices.size();
                for (const auto &[start, _] : boundary_next)
                {
                    if (visited_boundary.count(start))
                        continue;
                    std::vector<uint32_t> loop;
                    uint32_t cur = start;
                    bool loop_valid = true;
                    while (true)
                    {
                        if (visited_boundary.count(cur))
                        {
                            if (!loop.empty() && cur == loop.front())
                                break;
                            loop_valid = false;
                            break;
                        }
                        visited_boundary.insert(cur);
                        loop.push_back(cur);
                        auto it = boundary_next.find(cur);
                        if (it == boundary_next.end())
                        {
                            loop_valid = false;
                            break;
                        }
                        cur = it->second;
                        if (loop.size() > max_loop_size)
                        {
                            loop_valid = false;
                            break;
                        }
                    }
                    if (!loop_valid || loop.size() < 3)
                    {
                        loops.clear();
                        break;
                    }
                    loops.push_back(std::move(loop));
                }
                if (loops.empty())
                    continue;
                bool has_collinear = false;
                const double COLLINEAR_TOL = 0.001;
                for (const auto &loop : loops)
                {
                    size_t n = loop.size();
                    if (n < 3)
                        continue;
                    for (size_t i = 0; i < n; ++i)
                    {
                        Vec3 prev(mesh.vertices[loop[(i + n - 1) % n]]);
                        Vec3 curr(mesh.vertices[loop[i]]);
                        Vec3 next(mesh.vertices[loop[(i + 1) % n]]);
                        Vec3 seg = next - prev;
                        double seg_len = seg.length();
                        if (seg_len < 1e-12)
                            continue;
                        Vec3 to_curr = curr - prev;
                        Vec3 cross = seg.cross(to_curr);
                        double dist = cross.length() / seg_len;
                        if (dist < COLLINEAR_TOL)
                        {
                            double t = to_curr.dot(seg) / (seg_len * seg_len);
                            if (t > 0.01 && t < 0.99)
                            {
                                has_collinear = true;
                                break;
                            }
                        }
                    }
                    if (has_collinear)
                        break;
                }
                if (!has_collinear)
                    continue;
                Vec3 ref_n = face_normals[group[0]];
                int drop_axis;
                double anx = std::abs(ref_n.x), any = std::abs(ref_n.y), anz = std::abs(ref_n.z);
                if (anx >= any && anx >= anz)
                    drop_axis = 0;
                else if (any >= anx && any >= anz)
                    drop_axis = 1;
                else
                    drop_axis = 2;
                constexpr int axis_map[3][2] = {{1, 2}, {0, 2}, {0, 1}};
                int ax0 = axis_map[drop_axis][0], ax1 = axis_map[drop_axis][1];
                auto signed_area_2d = [&](const std::vector<uint32_t> &loop) -> double
                {
                    double area = 0.0;
                    size_t n = loop.size();
                    for (size_t i = 0; i < n; ++i)
                    {
                        const auto &p0 = mesh.vertices[loop[i]];
                        const auto &p1 = mesh.vertices[loop[(i + 1) % n]];
                        area += p0[ax0] * p1[ax1] - p1[ax0] * p0[ax1];
                    }
                    return area * 0.5;
                };
                size_t outer_idx = 0;
                double max_abs_area = 0.0;
                std::vector<double> loop_areas(loops.size());
                for (size_t i = 0; i < loops.size(); ++i)
                {
                    loop_areas[i] = signed_area_2d(loops[i]);
                    if (std::abs(loop_areas[i]) > max_abs_area)
                    {
                        max_abs_area = std::abs(loop_areas[i]);
                        outer_idx = i;
                    }
                }
                double normal_sign = (drop_axis == 0) ? ref_n.x : (drop_axis == 1) ? ref_n.y
                                                                                   : ref_n.z;
                bool need_flip = (loop_areas[outer_idx] * normal_sign) < 0;
                if (need_flip)
                {
                    for (auto &loop : loops)
                        std::reverse(loop.begin(), loop.end());
                    for (auto &a : loop_areas)
                        a = -a;
                }
                using Point = std::array<double, 2>;
                std::vector<std::vector<Point>> polygon;
                std::vector<uint32_t> all_indices;
                polygon.emplace_back();
                for (uint32_t vi : loops[outer_idx])
                {
                    polygon.back().push_back({mesh.vertices[vi][ax0], mesh.vertices[vi][ax1]});
                    all_indices.push_back(vi);
                }
                for (size_t li = 0; li < loops.size(); ++li)
                {
                    if (li == outer_idx)
                        continue;
                    polygon.emplace_back();
                    auto hole_loop = loops[li];
                    if (loop_areas[li] > 0)
                        std::reverse(hole_loop.begin(), hole_loop.end());
                    for (uint32_t vi : hole_loop)
                    {
                        polygon.back().push_back({mesh.vertices[vi][ax0], mesh.vertices[vi][ax1]});
                        all_indices.push_back(vi);
                    }
                }
                mapbox::detail::Earcut<uint32_t> ec;
                ec(polygon);
                if (ec.indices.empty() || ec.indices.size() % 3 != 0)
                    continue;
                bool earcut_valid = true;
                for (uint32_t idx : ec.indices)
                {
                    if (idx >= all_indices.size())
                    {
                        earcut_valid = false;
                        break;
                    }
                }
                if (!earcut_valid)
                    continue;
                for (size_t fi : group)
                    face_removed[fi] = true;
                for (size_t i = 0; i < ec.indices.size(); i += 3)
                {
                    uint32_t a = all_indices[ec.indices[i]];
                    uint32_t b = all_indices[ec.indices[i + 1]];
                    uint32_t c = all_indices[ec.indices[i + 2]];
                    if (a != b && b != c && a != c)
                    {
                        new_faces_to_add.push_back({a, b, c});
                    }
                }
            }
            if (!new_faces_to_add.empty())
            {
                std::vector<std::array<uint32_t, 3>> final_faces;
                final_faces.reserve(mesh.faces.size());
                for (size_t fi = 0; fi < nf; ++fi)
                {
                    if (!face_removed[fi])
                        final_faces.push_back(mesh.faces[fi]);
                }
                for (auto &f : new_faces_to_add)
                    final_faces.push_back(f);
                mesh.faces = std::move(final_faces);
            }
        }
        void append_verts_f(std::vector<std::array<float, 3>> &out, const CppMeshData &mesh)
        {
            for (const auto &v : mesh.vertices)
                out.push_back({static_cast<float>(v[0]),
                               static_cast<float>(v[1]),
                               static_cast<float>(v[2])});
        }
        std::vector<std::array<float, 3>> collect_input_verts_f(
            const CppMeshData &mesh)
        {
            std::vector<std::array<float, 3>> verts;
            verts.reserve(mesh.vertices.size());
            append_verts_f(verts, mesh);
            return verts;
        }
        std::vector<std::array<float, 3>> collect_input_verts_f(
            const CppMeshData &mesh1, const CppMeshData &mesh2)
        {
            std::vector<std::array<float, 3>> verts;
            verts.reserve(mesh1.vertices.size() + mesh2.vertices.size());
            append_verts_f(verts, mesh1);
            append_verts_f(verts, mesh2);
            return verts;
        }
        CppMeshData finalize_result(CppMeshData mesh,
                                    const std::vector<std::array<float, 3>> &input_verts)
        {
            snap_to_input_vertices(mesh, input_verts, kSnapTol);
            collapse_short_edges(mesh, kSnapTol);
            retri_coplanar_patches(mesh);
            fix_face_winding(mesh);
            return mesh;
        }
    }
    bool aabb_intersects(const CppMeshData &a, const CppMeshData &b)
    {
        if (!a.is_valid() || !b.is_valid())
        {
            return false;
        }
        auto aabb_a = a.compute_aabb();
        auto aabb_b = b.compute_aabb();
        return aabb_a.intersects(aabb_b);
    }
    std::optional<CppMeshData> boolean_difference(
        const CppMeshData &positive,
        const CppMeshData &negative)
    {
        if (!positive.is_valid())
        {
            return std::nullopt;
        }
        if (!negative.is_valid())
        {
            return positive;
        }
        if (!aabb_intersects(positive, negative))
        {
            return positive;
        }
        try
        {
            auto input_verts = collect_input_verts_f(positive, negative);
            manifold::Manifold pos_manifold = to_manifold(positive);
            manifold::Manifold neg_manifold = to_manifold(negative);
            if (pos_manifold.Status() != manifold::Manifold::Error::NoError)
            {
                return positive;
            }
            if (neg_manifold.Status() != manifold::Manifold::Error::NoError)
            {
                return positive;
            }
            manifold::Manifold result = pos_manifold - neg_manifold;
            if (result.IsEmpty())
            {
                return std::nullopt;
            }
            if (result.Status() != manifold::Manifold::Error::NoError)
            {
                return positive;
            }
            CppMeshData result_mesh = from_manifold(result);
            if (!result_mesh.is_valid())
            {
                return std::nullopt;
            }
            return finalize_result(std::move(result_mesh), input_verts);
        }
        catch (const std::exception &)
        {
            return positive;
        }
    }
    std::optional<CppMeshData> boolean_difference_batch(
        const CppMeshData &positive,
        const std::vector<CppMeshData> &negatives)
    {
        if (!positive.is_valid())
        {
            return std::nullopt;
        }
        if (negatives.empty())
        {
            return positive;
        }
        try
        {
            manifold::Manifold current = to_manifold(positive);
            if (current.Status() != manifold::Manifold::Error::NoError)
            {
                return positive;
            }
            std::vector<std::array<float, 3>> input_verts = collect_input_verts_f(positive);
            auto positive_aabb = positive.compute_aabb();
            for (const auto &negative : negatives)
            {
                if (!negative.is_valid())
                {
                    continue;
                }
                auto neg_aabb = negative.compute_aabb();
                if (!positive_aabb.intersects(neg_aabb))
                {
                    continue;
                }
                append_verts_f(input_verts, negative);
                manifold::Manifold neg_manifold = to_manifold(negative);
                if (neg_manifold.Status() != manifold::Manifold::Error::NoError)
                {
                    continue;
                }
                current = current - neg_manifold;
                if (current.IsEmpty())
                {
                    return std::nullopt;
                }
            }
            CppMeshData result = from_manifold(current);
            if (!result.is_valid())
            {
                return std::nullopt;
            }
            return finalize_result(std::move(result), input_verts);
        }
        catch (const std::exception &)
        {
            return positive;
        }
    }
    std::optional<CppMeshData> boolean_union(
        const CppMeshData &mesh1,
        const CppMeshData &mesh2)
    {
        if (!mesh1.is_valid() && !mesh2.is_valid())
        {
            return std::nullopt;
        }
        if (!mesh1.is_valid())
        {
            return mesh2;
        }
        if (!mesh2.is_valid())
        {
            return mesh1;
        }
        try
        {
            auto input_verts = collect_input_verts_f(mesh1, mesh2);
            manifold::Manifold m1 = to_manifold(mesh1);
            manifold::Manifold m2 = to_manifold(mesh2);
            if (m1.Status() != manifold::Manifold::Error::NoError)
            {
                return mesh2;
            }
            if (m2.Status() != manifold::Manifold::Error::NoError)
            {
                return mesh1;
            }
            manifold::Manifold result = m1 + m2;
            if (result.IsEmpty() || result.Status() != manifold::Manifold::Error::NoError)
            {
                return std::nullopt;
            }
            CppMeshData result_mesh = from_manifold(result);
            return finalize_result(std::move(result_mesh), input_verts);
        }
        catch (const std::exception &)
        {
            return std::nullopt;
        }
    }
    std::optional<CppMeshData> boolean_intersection(
        const CppMeshData &mesh1,
        const CppMeshData &mesh2)
    {
        if (!mesh1.is_valid() || !mesh2.is_valid())
        {
            return std::nullopt;
        }
        if (!aabb_intersects(mesh1, mesh2))
        {
            return std::nullopt;
        }
        try
        {
            auto input_verts = collect_input_verts_f(mesh1, mesh2);
            manifold::Manifold m1 = to_manifold(mesh1);
            manifold::Manifold m2 = to_manifold(mesh2);
            if (m1.Status() != manifold::Manifold::Error::NoError ||
                m2.Status() != manifold::Manifold::Error::NoError)
            {
                return std::nullopt;
            }
            manifold::Manifold result = m1 ^ m2;
            if (result.IsEmpty() || result.Status() != manifold::Manifold::Error::NoError)
            {
                return std::nullopt;
            }
            CppMeshData result_mesh = from_manifold(result);
            return finalize_result(std::move(result_mesh), input_verts);
        }
        catch (const std::exception &)
        {
            return std::nullopt;
        }
    }
}
