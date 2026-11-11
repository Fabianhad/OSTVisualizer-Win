#include "renderer.hpp"
#include <glad/glad.h>
#include <glm/glm.hpp>
#include <glm/gtc/matrix_transform.hpp>
#include <glm/gtc/type_ptr.hpp>
#include <algorithm>
#include <cstddef>
#include <cstring>
#include <cmath>
#include <chrono>
#include <stdexcept>
#include <unordered_map>
#include <array>
#include <climits>
#include <cstdint>
#include "earcut/earcut.hpp"
#include "instanced_model.hpp"
#ifdef _WIN32
#include <windows.h>
#include <functional>
#include <glm/gtc/constants.hpp>
#endif
namespace ost_renderer
{
    namespace
    {
        void unpack_vec3(std::vector<Vec3> &out, const std::vector<float> &flat)
        {
            out.clear();
            out.reserve(flat.size() / 3);
            for (size_t i = 0; i + 2 < flat.size(); i += 3)
                out.emplace_back(flat[i], flat[i + 1], flat[i + 2]);
        }
#ifdef _WIN32
        class ContextGuard
        {
            HDC prev_hdc_;
            HGLRC prev_hglrc_;
            bool switched_;

        public:
            ContextGuard(void *hdc, void *hglrc)
                : prev_hdc_(wglGetCurrentDC()),
                  prev_hglrc_(wglGetCurrentContext()),
                  switched_(false)
            {
                auto target_hdc = static_cast<HDC>(hdc);
                auto target_hglrc = static_cast<HGLRC>(hglrc);
                if (target_hglrc && target_hglrc != prev_hglrc_)
                {
                    wglMakeCurrent(target_hdc, target_hglrc);
                    switched_ = true;
                }
            }
            ~ContextGuard()
            {
                if (switched_)
                    wglMakeCurrent(prev_hdc_, prev_hglrc_);
            }
            ContextGuard(const ContextGuard &) = delete;
            ContextGuard &operator=(const ContextGuard &) = delete;
        };
#else
        class ContextGuard
        {
        public:
            ContextGuard(void *, void *) {}
        };
#endif
        std::vector<uint32_t> feature_edge_indices(const std::vector<Vec3> &vertices,
                                                   const std::vector<uint32_t> &indices)
        {
            int triCount = (int)(indices.size() / 3);
            struct PositionKey
            {
                long long x, y, z;
                bool operator==(const PositionKey &o) const { return x == o.x && y == o.y && z == o.z; }
            };
            struct PositionKeyHash
            {
                size_t operator()(const PositionKey &k) const
                {
                    size_t h = std::hash<long long>{}(k.x);
                    h ^= std::hash<long long>{}(k.y) + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2);
                    h ^= std::hash<long long>{}(k.z) + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2);
                    return h;
                }
            };
            const double positionPrecision = 1.0e4;
            std::vector<uint32_t> canonical(vertices.size());
            std::unordered_map<PositionKey, uint32_t, PositionKeyHash> positionIds;
            positionIds.reserve(vertices.size());
            for (size_t i = 0; i < vertices.size(); ++i)
            {
                const auto &p = vertices[i];
                if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z))
                {
                    canonical[i] = (uint32_t)i;
                    continue;
                }
                PositionKey key{
                    std::llround((double)p.x * positionPrecision),
                    std::llround((double)p.y * positionPrecision),
                    std::llround((double)p.z * positionPrecision)};
                canonical[i] = positionIds.emplace(key, (uint32_t)i).first->second;
            }
            struct EdgeInfo
            {
                int face;
                uint32_t v0, v1;
            };
            std::unordered_map<uint64_t, EdgeInfo> edgeMap;
            std::vector<uint32_t> lineIndices;
            const float creaseThreshold = cosf(15.0f * 3.14159f / 180.0f);
            auto faceNormal = [&](int t) -> glm::vec3
            {
                auto &a = vertices[indices[t * 3]];
                auto &b = vertices[indices[t * 3 + 1]];
                auto &c = vertices[indices[t * 3 + 2]];
                glm::vec3 e1(b.x - a.x, b.y - a.y, b.z - a.z);
                glm::vec3 e2(c.x - a.x, c.y - a.y, c.z - a.z);
                return glm::normalize(glm::cross(e1, e2));
            };
            for (int t = 0; t < triCount; t++)
            {
                uint32_t idx[3] = {indices[t * 3], indices[t * 3 + 1], indices[t * 3 + 2]};
                for (int e = 0; e < 3; e++)
                {
                    uint32_t va = idx[e], vb = idx[(e + 1) % 3];
                    uint32_t ca = canonical[va], cb = canonical[vb];
                    if (ca == cb)
                        continue;
                    uint64_t key = ((uint64_t)std::min(ca, cb) << 32) | std::max(ca, cb);
                    auto it = edgeMap.find(key);
                    if (it == edgeMap.end())
                    {
                        edgeMap[key] = {t, va, vb};
                    }
                    else
                    {
                        glm::vec3 n1 = faceNormal(it->second.face);
                        glm::vec3 n2 = faceNormal(t);
                        if (glm::dot(n1, n2) < creaseThreshold)
                        {
                            lineIndices.push_back(it->second.v0);
                            lineIndices.push_back(it->second.v1);
                        }
                        edgeMap.erase(it);
                    }
                }
            }
            for (auto &kv : edgeMap)
            {
                lineIndices.push_back(kv.second.v0);
                lineIndices.push_back(kv.second.v1);
            }
            return lineIndices;
        }
        void reset_instance_attributes()
        {
            glVertexAttrib4f(3, 1.0f, 0.0f, 0.0f, 0.0f);
            glVertexAttrib4f(4, 0.0f, 1.0f, 0.0f, 0.0f);
            glVertexAttrib4f(5, 0.0f, 0.0f, 1.0f, 0.0f);
            glVertexAttrib4f(6, 0.0f, 0.0f, 0.0f, 0.0f);
        }
    }
    void Box3::expand(const Vec3 &point)
    {
        if (is_empty())
        {
            min = max = point;
        }
        else
        {
            min.x = std::min(min.x, point.x);
            min.y = std::min(min.y, point.y);
            min.z = std::min(min.z, point.z);
            max.x = std::max(max.x, point.x);
            max.y = std::max(max.y, point.y);
            max.z = std::max(max.z, point.z);
        }
    }
    void Box3::clear()
    {
        min = Vec3(kMaxFloat, kMaxFloat, kMaxFloat);
        max = Vec3(-kMaxFloat, -kMaxFloat, -kMaxFloat);
    }
    void MeshData::set_vertices(const std::vector<float> &flat_verts)
    {
        if (flat_verts.size() % 3 != 0)
            throw std::invalid_argument(
                "Mesh vertex array length must be divisible by 3");
        unpack_vec3(vertices, flat_verts);
    }
    void MeshData::set_normals(const std::vector<float> &flat_norms)
    {
        if (flat_norms.size() % 3 != 0)
            throw std::invalid_argument(
                "Mesh normal array length must be divisible by 3");
        unpack_vec3(normals, flat_norms);
    }
    Camera::Camera()
    {
        reset();
    }
    void Camera::interpolate(float alpha)
    {
        interpolation_alpha = alpha;
    }
    bool Camera::has_velocity() const
    {
        return std::abs(rotational_velocity.x) > 0.0001f ||
               std::abs(rotational_velocity.y) > 0.0001f ||
               glm::length(pan_velocity) > 0.0001f;
    }
    void Camera::rotate(float delta_x, float delta_y)
    {
        rotational_velocity.x -= delta_x * 0.001f;
        rotational_velocity.y += delta_y * 0.001f;
        const float max_vel = 0.4f;
        rotational_velocity.x = glm::clamp(rotational_velocity.x, -max_vel, max_vel);
        rotational_velocity.y = glm::clamp(rotational_velocity.y, -max_vel, max_vel);
    }
    void Camera::pan(float delta_x, float delta_y)
    {
        glm::vec3 forward = glm::normalize(target.to_glm() - position.to_glm());
        glm::vec3 world_up(0, 0, 1);
        glm::vec3 right = glm::cross(forward, world_up);
        if (glm::length(right) > 0.001f)
        {
            right = glm::normalize(right);
        }
        else
        {
            right = glm::vec3(1, 0, 0);
        }
        glm::vec3 up = glm::cross(right, forward);
        float distance = glm::distance(position.to_glm(), target.to_glm());
        float scale = distance * 0.001f;
        pan_velocity += right * (-delta_x * scale * 0.2f);
        pan_velocity += up * (delta_y * scale * 0.2f);
        const float max_pan = distance * 0.05f;
        if (glm::length(pan_velocity) > max_pan)
        {
            pan_velocity = glm::normalize(pan_velocity) * max_pan;
        }
    }
    void Camera::update(float delta_time)
    {
        prev_position = position;
        prev_target = target;
        const float target_fps = 60.0f;
        const float rot_damping_per_frame = 0.75f;
        const float pan_damping_per_frame = 0.75f;
        float rot_damping = std::pow(rot_damping_per_frame, delta_time * target_fps);
        float pan_damping = std::pow(pan_damping_per_frame, delta_time * target_fps);
        if (std::abs(rotational_velocity.x) > 0.0001f || std::abs(rotational_velocity.y) > 0.0001f)
        {
            glm::vec3 offset = position.to_glm() - target.to_glm();
            float radius = glm::length(offset);
            if (radius >= 0.001f)
            {
                float azimuth = atan2(offset.y, offset.x);
                float elevation = asin(glm::clamp(offset.z / radius, -1.0f, 1.0f));
                azimuth += rotational_velocity.x;
                elevation += rotational_velocity.y;
                elevation = glm::clamp(elevation, -glm::pi<float>() / 2.0f + 0.1f, glm::pi<float>() / 2.0f - 0.1f);
                position.x = target.x + radius * cos(elevation) * cos(azimuth);
                position.y = target.y + radius * cos(elevation) * sin(azimuth);
                position.z = target.z + radius * sin(elevation);
            }
            rotational_velocity.x *= rot_damping;
            rotational_velocity.y *= rot_damping;
            if (std::abs(rotational_velocity.x) < 0.0001f)
                rotational_velocity.x = 0.0f;
            if (std::abs(rotational_velocity.y) < 0.0001f)
                rotational_velocity.y = 0.0f;
        }
        if (glm::length(pan_velocity) > 0.0001f)
        {
            glm::vec3 pan = pan_velocity;
            position = Vec3::from_glm(position.to_glm() + pan);
            target = Vec3::from_glm(target.to_glm() + pan);
            pan_velocity *= pan_damping;
            if (glm::length(pan_velocity) < 0.001f)
            {
                pan_velocity = glm::vec3(0.0f);
            }
        }
    }
    void Camera::zoom(float delta)
    {
        glm::vec3 direction = target.to_glm() - position.to_glm();
        float distance = glm::length(direction);
        if (distance < 0.001f)
            return;
        direction = glm::normalize(direction);
        float zoom_amount = delta * distance * 0.001f;
        float new_distance = glm::clamp(distance - zoom_amount, near_plane * 2.0f, far_plane * 0.5f);
        position = Vec3::from_glm(target.to_glm() - direction * new_distance);
        prev_position = position;
    }
    float Camera::configure_clip_planes(const Box3 &bounds)
    {
        if (bounds.is_empty())
            return 0.0f;
        float size = std::max({bounds.max.x - bounds.min.x,
                               bounds.max.y - bounds.min.y,
                               bounds.max.z - bounds.min.z});
        if (size < 1.0f)
            size = 100.0f;
        near_plane = std::max(0.1f, size * 0.001f);
        far_plane = std::max(10000.0f, size * 20.0f);
        return size;
    }
    void Camera::show_object(const Box3 &bounds)
    {
        if (bounds.is_empty())
        {
            reset();
            return;
        }
        float size = configure_clip_planes(bounds);
        Vec3 center(
            (bounds.min.x + bounds.max.x) * 0.5f,
            (bounds.min.y + bounds.max.y) * 0.5f,
            (bounds.min.z + bounds.max.z) * 0.5f);
        target = center;
        position.x = center.x;
        position.y = center.y + size;
        position.z = center.z + size * 1.5f;
        prev_position = position;
        prev_target = target;
    }
    void Camera::restore_state(const Vec3 &saved_position,
                               const Vec3 &saved_target,
                               float saved_fov,
                               const Box3 &bounds)
    {
        configure_clip_planes(bounds);
        position = saved_position;
        target = saved_target;
        prev_position = position;
        prev_target = target;
        fov = saved_fov;
        rotational_velocity = glm::vec2(0.0f);
        pan_velocity = glm::vec3(0.0f);
        interpolation_alpha = 0.0f;
    }
    void Camera::reset()
    {
        position = Vec3(0, 1000, 1500);
        target = Vec3(0, 0, 0);
        prev_position = position;
        prev_target = target;
        fov = 45.0f;
        rotational_velocity = glm::vec2(0.0f);
        pan_velocity = glm::vec3(0.0f);
        interpolation_alpha = 0.0f;
    }
    void Camera::get_view_matrix(float *out_matrix) const
    {
        float t = glm::clamp(interpolation_alpha, 0.0f, 1.0f);
        glm::vec3 interp_pos = glm::mix(prev_position.to_glm(), position.to_glm(), t);
        glm::vec3 interp_target = glm::mix(prev_target.to_glm(), target.to_glm(), t);
        glm::mat4 view = glm::lookAt(interp_pos, interp_target, glm::vec3(0, 0, 1));
        std::memcpy(out_matrix, glm::value_ptr(view), 16 * sizeof(float));
    }
    void Camera::get_projection_matrix(float *out_matrix) const
    {
        glm::mat4 proj = glm::perspective(
            glm::radians(fov),
            aspect_ratio,
            near_plane,
            far_plane);
        std::memcpy(out_matrix, glm::value_ptr(proj), 16 * sizeof(float));
    }
    const std::string Scene::kEmptyString;
    void Scene::attach_gl_context(void *hdc, void *hglrc)
    {
        gl_hdc_ = hdc;
        gl_hglrc_ = hglrc;
    }
    void Scene::clear()
    {
        ContextGuard guard(gl_hdc_, gl_hglrc_);
        for (auto &m : meshes_)
        {
            if (m.vao)
                glDeleteVertexArrays(1, &m.vao);
            if (m.vbo)
                glDeleteBuffers(1, &m.vbo);
            if (m.ebo)
                glDeleteBuffers(1, &m.ebo);
            if (m.line_vao)
                glDeleteVertexArrays(1, &m.line_vao);
            if (m.line_ibo)
                glDeleteBuffers(1, &m.line_ibo);
        }
        meshes_.clear();
        instances_.clear();
        layouts_.clear();
        bounds_.clear();
        selected_.clear();
        ++revision_;
        ++instance_revision_;
    }
    int Scene::add_model_layout(const std::vector<std::string> &components, const std::vector<float> &matrices)
    {
        if (matrices.size() != components.size() * 12)
            throw std::invalid_argument("A model layout needs 12 matrix values per component");
        ModelLayout layout;
        layout.items.reserve(components.size());
        for (size_t i = 0; i < components.size(); ++i)
        {
            ModelLayoutItem item;
            item.component = components[i];
            for (size_t k = 0; k < 12; ++k)
            {
                float value = matrices[i * 12 + k];
                if (!std::isfinite(value))
                    throw std::invalid_argument("Model layout matrices must be finite");
                item.matrix[k] = value;
            }
            layout.items.push_back(std::move(item));
        }
        layouts_.push_back(std::move(layout));
        ++instance_revision_;
        return (int)layouts_.size() - 1;
    }
    void Scene::add_model_instance(const Vec3 &position, float rotation, const Color &tint, int layout)
    {
        if (!std::isfinite(position.x) || !std::isfinite(position.y) || !std::isfinite(position.z) ||
            !std::isfinite(rotation))
            throw std::invalid_argument("Model instance position and rotation must be finite");
        if (layout < -1 || layout >= (int)layouts_.size())
            throw std::invalid_argument("Model instance layout does not exist");
        instances_.push_back(ModelInstance{position, rotation, tint, layout});
        ++instance_revision_;
    }
    void Scene::add_mesh(const MeshData &data)
    {
        if (data.vertices.empty() || data.indices.empty())
            return;
        if (data.indices.size() % 3 != 0)
            throw std::invalid_argument(
                "Mesh index array length must be divisible by 3");
        if (std::any_of(
                data.indices.begin(),
                data.indices.end(),
                [&data](uint32_t index)
                { return index >= data.vertices.size(); }))
            throw std::invalid_argument(
                "Mesh index is outside the vertex array");
        ContextGuard guard(gl_hdc_, gl_hglrc_);
        GLMesh mesh;
        mesh.index_count = data.indices.size();
        mesh.transparent = data.color.a < 0.99f;
        mesh.mesh_index = (int)meshes_.size();
        mesh.color = data.color;
        mesh.condition_uid = data.condition_uid;
        mesh.takeoff_uid = data.takeoff_uid;
        mesh.positions.reserve(data.vertices.size() * 3);
        for (const auto &v : data.vertices)
        {
            mesh.positions.push_back(v.x);
            mesh.positions.push_back(v.y);
            mesh.positions.push_back(v.z);
        }
        mesh.indices = data.indices;
        struct Vertex
        {
            float x, y, z, nx, ny, nz, r, g, b, a;
        };
        std::vector<Vertex> verts;
        verts.reserve(data.vertices.size());
        for (size_t i = 0; i < data.vertices.size(); ++i)
        {
            const auto &pos = data.vertices[i];
            Vertex v;
            v.x = pos.x;
            v.y = pos.y;
            v.z = pos.z;
            bounds_.expand(pos);
            if (i < data.normals.size())
            {
                v.nx = data.normals[i].x;
                v.ny = data.normals[i].y;
                v.nz = data.normals[i].z;
            }
            else
            {
                v.nx = v.ny = 0;
                v.nz = 1;
            }
            v.r = data.color.r;
            v.g = data.color.g;
            v.b = data.color.b;
            v.a = data.color.a;
            verts.push_back(v);
        }
        glGenVertexArrays(1, &mesh.vao);
        glGenBuffers(1, &mesh.vbo);
        glGenBuffers(1, &mesh.ebo);
        glBindVertexArray(mesh.vao);
        glBindBuffer(GL_ARRAY_BUFFER, mesh.vbo);
        glBufferData(GL_ARRAY_BUFFER, verts.size() * sizeof(Vertex), verts.data(), GL_STATIC_DRAW);
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, mesh.ebo);
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, data.indices.size() * sizeof(uint32_t),
                     data.indices.data(), GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex), 0);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex), (void *)offsetof(Vertex, nx));
        glEnableVertexAttribArray(2);
        glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, sizeof(Vertex), (void *)offsetof(Vertex, r));
        glBindVertexArray(0);
        int triCount = (int)(data.indices.size() / 3);
        if (triCount > 0)
        {
            std::vector<uint32_t> lineIndices = feature_edge_indices(data.vertices, data.indices);
            if (!lineIndices.empty())
            {
                mesh.line_count = lineIndices.size();
                glGenVertexArrays(1, &mesh.line_vao);
                glGenBuffers(1, &mesh.line_ibo);
                glBindVertexArray(mesh.line_vao);
                glBindBuffer(GL_ARRAY_BUFFER, mesh.vbo);
                glEnableVertexAttribArray(0);
                glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex), 0);
                glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, mesh.line_ibo);
                glBufferData(GL_ELEMENT_ARRAY_BUFFER,
                             lineIndices.size() * sizeof(uint32_t), lineIndices.data(), GL_STATIC_DRAW);
                glBindVertexArray(0);
            }
        }
        meshes_.push_back(mesh);
        ++revision_;
    }
    Box3 Scene::get_bounds() const { return bounds_; }
    const std::string &Scene::get_condition_uid(int index) const
    {
        if (index < 0 || index >= (int)meshes_.size())
            return kEmptyString;
        return meshes_[index].condition_uid;
    }
    const std::string &Scene::get_takeoff_uid(int index) const
    {
        if (index < 0 || index >= (int)meshes_.size())
            return kEmptyString;
        return meshes_[index].takeoff_uid;
    }
    void Scene::set_selected(int mesh_index, bool selected)
    {
        if (selected)
            selected_.insert(mesh_index);
        else
            selected_.erase(mesh_index);
    }
    void Scene::clear_selection() { selected_.clear(); }
    const char *mesh_vertex_shader = R"(
#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec4 aColor;
layout (location = 3) in vec4 aRow0;
layout (location = 4) in vec4 aRow1;
layout (location = 5) in vec4 aRow2;
layout (location = 6) in vec4 aTint;
out vec4 vertexColor;
out vec3 normal;
out vec3 worldPos;
out float vTinted;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    vec4 local = vec4(aPos, 1.0);
    vec3 placed = vec3(dot(aRow0, local), dot(aRow1, local), dot(aRow2, local));
    vec3 placedNormal = vec3(dot(cross(aRow1.xyz, aRow2.xyz), aNormal),
                             dot(cross(aRow2.xyz, aRow0.xyz), aNormal),
                             dot(cross(aRow0.xyz, aRow1.xyz), aNormal));
    vec4 worldPosition = model * vec4(placed, 1.0);
    worldPos = worldPosition.xyz;
    normal = mat3(transpose(inverse(model))) * placedNormal;
    vertexColor = aTint.a > 0.0 ? vec4(aTint.rgb, aColor.a) : aColor;
    vTinted = aTint.a > 0.0 ? 1.0 : 0.0;
    gl_Position = projection * view * worldPosition;
}
)";
    const char *opaque_fragment_shader = R"(
#version 330 core
in vec4 vertexColor;
in vec3 normal;
in vec3 worldPos;
out vec4 FragColor;
uniform vec4 sectionCut;
bool sectionCutRemoved(vec3 p) {
    return (sectionCut.x > 0.5 && p.y > sectionCut.y) || (sectionCut.z > 0.5 && p.x > sectionCut.w);
}
uniform float ambientIntensity = 0.55;
uniform vec3 keyLightDir = normalize(vec3(500.0, -500.0, 500.0));
uniform float keyLightIntensity = 0.45;
uniform vec3 fillLightDir = normalize(vec3(-500.0, 500.0, 500.0));
uniform float fillLightIntensity = 0.35;
uniform vec3 rimLightDir = normalize(vec3(0.0, 500.0, -500.0));
uniform float rimLightIntensity = 0.2;
void main() {
    if (sectionCutRemoved(worldPos)) discard;
    vec3 norm = normalize(normal);
    vec3 ambient = ambientIntensity * vec3(1.0);
    float keyDiff = max(dot(norm, normalize(keyLightDir)), 0.0);
    vec3 keyDiffuse = keyLightIntensity * keyDiff * vec3(1.0);
    float fillDiff = max(dot(norm, normalize(fillLightDir)), 0.0);
    vec3 fillDiffuse = fillLightIntensity * fillDiff * vec3(1.0);
    float rimDiff = max(dot(norm, normalize(rimLightDir)), 0.0);
    vec3 rimDiffuse = rimLightIntensity * rimDiff * vec3(1.0);
    vec3 lighting = ambient + keyDiffuse + fillDiffuse + rimDiffuse;
    vec3 result = lighting * vertexColor.rgb;
    FragColor = vec4(result, vertexColor.a);
}
)";
    const char *transparent_accum_fragment_shader = R"(
#version 330 core
in vec4 vertexColor;
in vec3 normal;
in vec3 worldPos;
layout(location = 0) out vec4 accumColor;
layout(location = 1) out float revealage;
uniform vec4 sectionCut;
bool sectionCutRemoved(vec3 p) {
    return (sectionCut.x > 0.5 && p.y > sectionCut.y) || (sectionCut.z > 0.5 && p.x > sectionCut.w);
}
uniform float ambientIntensity = 0.55;
uniform vec3 keyLightDir = normalize(vec3(500.0, -500.0, 500.0));
uniform float keyLightIntensity = 0.45;
uniform vec3 fillLightDir = normalize(vec3(-500.0, 500.0, 500.0));
uniform float fillLightIntensity = 0.35;
uniform vec3 rimLightDir = normalize(vec3(0.0, 500.0, -500.0));
uniform float rimLightIntensity = 0.2;
float weight(float alpha, float z) {
    return alpha * max(1e-2, 3e3 * pow(1.0 - z, 3.0));
}
void main() {
    if (sectionCutRemoved(worldPos)) discard;
    vec3 norm = normalize(normal);
    vec3 ambient = ambientIntensity * vec3(1.0);
    float keyDiff = max(dot(norm, normalize(keyLightDir)), 0.0);
    vec3 keyDiffuse = keyLightIntensity * keyDiff * vec3(1.0);
    float fillDiff = max(dot(norm, normalize(fillLightDir)), 0.0);
    vec3 fillDiffuse = fillLightIntensity * fillDiff * vec3(1.0);
    float rimDiff = max(dot(norm, normalize(rimLightDir)), 0.0);
    vec3 rimDiffuse = rimLightIntensity * rimDiff * vec3(1.0);
    vec3 lighting = ambient + keyDiffuse + fillDiffuse + rimDiffuse;
    vec3 color = lighting * vertexColor.rgb;
    float alpha = vertexColor.a;
    float z = gl_FragCoord.z;
    float w = weight(alpha, z);
    accumColor = vec4(color * alpha, alpha) * w;
    revealage = alpha * w;
}
)";
    const char *quad_vertex_shader = R"(
#version 330 core
layout (location = 0) in vec2 aPos;
layout (location = 1) in vec2 aTexCoord;
out vec2 texCoord;
void main() {
    texCoord = aTexCoord;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
)";
    const char *plan_texture_vertex_shader = R"(
#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec2 aTexCoord;
out vec2 texCoord;
uniform mat4 view;
uniform mat4 projection;
void main() {
    texCoord = aTexCoord;
    gl_Position = projection * view * vec4(aPos, 1.0);
}
)";
    const char *plan_texture_fragment_shader = R"(
#version 330 core
in vec2 texCoord;
out vec4 FragColor;
uniform sampler2D planTexture;
uniform float opacity;
void main() {
    vec4 color = texture(planTexture, texCoord);
    FragColor = vec4(color.rgb, color.a * opacity);
}
)";
    const char *composite_fragment_shader = R"(
#version 330 core
in vec2 texCoord;
out vec4 FragColor;
uniform sampler2D accumTexture;
uniform sampler2D revealageTexture;
uniform sampler2D opaqueTexture;
void main() {
    vec4 accum = texture(accumTexture, texCoord);
    float revealage = texture(revealageTexture, texCoord).r;
    vec4 opaque = texture(opaqueTexture, texCoord);
    if (accum.a <= 1e-5) {
        FragColor = opaque;
        return;
    }
    vec3 avgColor = accum.rgb / max(accum.a, 1e-5);
    float transmittance = max(1.0 - revealage, 1e-5);
    vec3 finalColor = avgColor * (1.0 - transmittance) + opaque.rgb * transmittance;
    FragColor = vec4(finalColor, 1.0);
}
)";
    const char *pick_fragment_shader = R"(
#version 330 core
in vec3 worldPos;
out vec4 FragColor;
uniform vec4 u_meshId;
uniform vec4 sectionCut;
bool sectionCutRemoved(vec3 p) {
    return (sectionCut.x > 0.5 && p.y > sectionCut.y) || (sectionCut.z > 0.5 && p.x > sectionCut.w);
}
void main() {
    if (sectionCutRemoved(worldPos)) discard;
    FragColor = u_meshId;
}
)";
    const char *flat_color_fragment_shader = R"(
#version 330 core
in vec3 worldPos;
in vec4 vertexColor;
in float vTinted;
out vec4 FragColor;
uniform vec4 u_color;
uniform float u_tintScale;
uniform vec4 sectionCut;
bool sectionCutRemoved(vec3 p) {
    return (sectionCut.x > 0.5 && p.y > sectionCut.y) || (sectionCut.z > 0.5 && p.x > sectionCut.w);
}
void main() {
    if (sectionCutRemoved(worldPos)) discard;
    FragColor = (u_tintScale > 0.0 && vTinted > 0.5) ? vec4(vertexColor.rgb * u_tintScale, 1.0) : u_color;
}
)";
    const char *selection_post_fragment_shader = R"(
#version 330 core
in vec2 texCoord;
out vec4 FragColor;
uniform sampler2D sceneTex;
uniform sampler2D selMaskTex;
void main() {
    vec4 scene = texture(sceneTex, texCoord);
    float sel = texture(selMaskTex, texCoord).r;
    if (sel < 0.5) {
        FragColor = scene;
        return;
    }
    FragColor = vec4(
        min(1.0, scene.r * 0.75 + 0.25),
        min(1.0, scene.g * 0.75 + 0.20),
        scene.b * 0.55,
        1.0
    );
}
)";

    namespace
    {
        struct CapVertex
        {
            float x, y, z, nx, ny, nz, r, g, b, a;
        };
        struct CutKey
        {
            long long u, v;
            bool operator==(const CutKey &o) const { return u == o.u && v == o.v; }
        };
        struct CutKeyHash
        {
            size_t operator()(const CutKey &k) const
            {
                size_t h = std::hash<long long>{}(k.u);
                h ^= std::hash<long long>{}(k.v) + 0x9e3779b97f4a7c15ULL + (h << 6) + (h >> 2);
                return h;
            }
        };
        using CutPoint = std::array<double, 2>;
        double ring_area(const std::vector<CutPoint> &ring)
        {
            double area = 0.0;
            for (size_t i = 0, j = ring.size() - 1; i < ring.size(); j = i++)
                area += (ring[j][0] - ring[i][0]) * (ring[j][1] + ring[i][1]);
            return area * 0.5;
        }
        bool ring_contains(const std::vector<CutPoint> &ring, const CutPoint &p)
        {
            bool inside = false;
            for (size_t i = 0, j = ring.size() - 1; i < ring.size(); j = i++)
            {
                const CutPoint &a = ring[i];
                const CutPoint &b = ring[j];
                if ((a[1] > p[1]) != (b[1] > p[1]) &&
                    p[0] < (b[0] - a[0]) * (p[1] - a[1]) / (b[1] - a[1]) + a[0])
                    inside = !inside;
            }
            return inside;
        }
    }
    void append_section_cap(const Scene::GLMesh &mesh, int axis, float plane, std::vector<CapVertex> &verts,
                            std::vector<uint32_t> &tris, std::vector<uint32_t> &lines)
    {
        const std::vector<float> &pos = mesh.positions;
        const std::vector<uint32_t> &idx = mesh.indices;
        const int ua = axis == 0 ? 1 : 0;
        const int va = 2;
        auto coord = [&](uint32_t i, int c)
        { return (double)pos[(size_t)i * 3 + c]; };
        auto before = [&](uint32_t a, uint32_t b)
        {
            for (int c = 0; c < 3; ++c)
            {
                double ca = coord(a, c), cb = coord(b, c);
                if (ca != cb)
                    return ca < cb;
            }
            return a < b;
        };
        struct Segment
        {
            CutPoint a, b;
        };
        std::vector<Segment> segments;
        for (size_t t = 0; t + 2 < idx.size(); t += 3)
        {
            uint32_t tri[3] = {idx[t], idx[t + 1], idx[t + 2]};
            double d[3];
            for (int k = 0; k < 3; ++k)
            {
                d[k] = coord(tri[k], axis) - plane;
                if (d[k] == 0.0)
                    d[k] = 1e-12;
            }
            CutPoint hits[2];
            int count = 0;
            for (int k = 0; k < 3 && count < 2; ++k)
            {
                int j = (k + 1) % 3;
                if ((d[k] > 0.0) == (d[j] > 0.0))
                    continue;
                uint32_t a = tri[k], b = tri[j];
                double da = d[k], db = d[j];
                if (before(b, a))
                {
                    std::swap(a, b);
                    std::swap(da, db);
                }
                double s = da / (da - db);
                hits[count][0] = coord(a, ua) + s * (coord(b, ua) - coord(a, ua));
                hits[count][1] = coord(a, va) + s * (coord(b, va) - coord(a, va));
                ++count;
            }
            if (count == 2)
                segments.push_back({hits[0], hits[1]});
        }
        if (segments.empty())
            return;
        const double quantum = 1.0e4;
        auto key_of = [&](const CutPoint &p)
        { return CutKey{std::llround(p[0] * quantum), std::llround(p[1] * quantum)}; };
        std::unordered_map<CutKey, std::vector<size_t>, CutKeyHash> at;
        std::vector<char> used(segments.size(), 0);
        for (size_t s = 0; s < segments.size(); ++s)
        {
            CutKey ka = key_of(segments[s].a), kb = key_of(segments[s].b);
            if (ka == kb)
            {
                used[s] = 1;
                continue;
            }
            at[ka].push_back(s);
            at[kb].push_back(s);
        }
        std::vector<std::vector<CutPoint>> loops;
        for (size_t s = 0; s < segments.size(); ++s)
        {
            if (used[s])
                continue;
            used[s] = 1;
            std::vector<CutPoint> loop{segments[s].a, segments[s].b};
            CutKey start = key_of(segments[s].a);
            CutKey current = key_of(segments[s].b);
            bool closed = false;
            for (size_t guard = 0; guard <= segments.size(); ++guard)
            {
                if (current == start)
                {
                    closed = true;
                    break;
                }
                auto found = at.find(current);
                if (found == at.end())
                    break;
                size_t next = SIZE_MAX;
                for (size_t candidate : found->second)
                    if (!used[candidate])
                    {
                        next = candidate;
                        break;
                    }
                if (next == SIZE_MAX)
                    break;
                used[next] = 1;
                const CutPoint &other = key_of(segments[next].a) == current ? segments[next].b : segments[next].a;
                loop.push_back(other);
                current = key_of(other);
            }
            if (!closed)
                continue;
            loop.pop_back();
            if (loop.size() >= 3 && std::abs(ring_area(loop)) > 1e-9)
                loops.push_back(std::move(loop));
        }
        if (loops.empty())
            return;
        const size_t n = loops.size();
        std::vector<double> areas(n);
        for (size_t i = 0; i < n; ++i)
            areas[i] = std::abs(ring_area(loops[i]));
        std::vector<int> parent(n, -1), depth(n, 0);
        for (size_t i = 0; i < n; ++i)
        {
            for (size_t j = 0; j < n; ++j)
            {
                if (i == j || areas[j] <= areas[i] || !ring_contains(loops[j], loops[i][0]))
                    continue;
                ++depth[i];
                if (parent[i] < 0 || areas[j] < areas[(size_t)parent[i]])
                    parent[i] = (int)j;
            }
        }
        const float normal[3] = {axis == 0 ? 1.0f : 0.0f, axis == 1 ? 1.0f : 0.0f, 0.0f};
        const float shade = 0.86f;
        for (size_t outer = 0; outer < n; ++outer)
        {
            if (depth[outer] % 2 != 0)
                continue;
            std::vector<std::vector<CutPoint>> polygon{loops[outer]};
            for (size_t h = 0; h < n; ++h)
                if (depth[h] % 2 != 0 && parent[h] == (int)outer)
                    polygon.push_back(loops[h]);
            std::vector<uint32_t> local = mapbox::earcut<uint32_t>(polygon);
            const uint32_t base = (uint32_t)verts.size();
            for (const auto &ring : polygon)
            {
                const uint32_t ring_base = (uint32_t)verts.size();
                for (const CutPoint &p : ring)
                {
                    float xyz[3];
                    xyz[axis] = plane;
                    xyz[ua] = (float)p[0];
                    xyz[va] = (float)p[1];
                    verts.push_back({xyz[0], xyz[1], xyz[2], normal[0], normal[1], normal[2],
                                     mesh.color.r * shade, mesh.color.g * shade, mesh.color.b * shade, mesh.color.a});
                }
                const uint32_t count = (uint32_t)ring.size();
                for (uint32_t k = 0; k < count; ++k)
                {
                    lines.push_back(ring_base + k);
                    lines.push_back(ring_base + (k + 1) % count);
                }
            }
            for (uint32_t i : local)
                tris.push_back(base + i);
        }
    }
    class Renderer::Impl
    {
    public:
        uintptr_t native_window = 0;
        int width = 800, height = 600;
        int samples = 0;
        GLuint opaque_shader = 0;
        GLuint transparent_accum_shader = 0;
        GLuint plan_texture_shader = 0;
        GLuint composite_shader = 0;
        GLuint accum_fbo = 0;
        GLuint accum_texture = 0;
        GLuint revealage_texture = 0;
        GLuint opaque_fbo = 0;
        GLuint opaque_texture = 0;
        GLuint depth_texture = 0;
        GLuint opaque_ms_fbo = 0;
        GLuint opaque_ms_color = 0;
        GLuint opaque_ms_depth = 0;
        GLuint quad_vao = 0, quad_vbo = 0;
        GLuint pick_fbo = 0, pick_color = 0, pick_depth_rb = 0;
        GLuint pick_shader_prog = 0;
        GLuint flat_color_shader_prog = 0;
        GLuint selection_post_shader_prog = 0;
        GLuint scene_fbo = 0, scene_texture = 0;
        GLuint sel_mask_fbo = 0, sel_mask_texture = 0;
        GLuint plan_texture = 0;
        GLuint plan_vao = 0;
        GLuint plan_vbo = 0;
        GLuint plan_ebo = 0;
        bool plan_texture_ready = false;
        bool plan_texture_visible = false;
        float plan_texture_opacity = 1.0f;
        bool show_edges = false;
        bool cut_enabled[2] = {false, false};
        float cut_position[2] = {0.0f, 0.0f};
        struct CapMesh
        {
            GLuint vao = 0, vbo = 0, ebo = 0, line_vao = 0, line_ebo = 0;
            GLsizei index_count = 0, line_count = 0;
            bool transparent = false;
            int mesh_index = -1;
            Color color;
        };
        std::vector<CapMesh> caps;
        struct ModelPartGL
        {
            GLuint vao = 0, vbo = 0, ebo = 0, line_vao = 0, line_ebo = 0;
            GLsizei index_count = 0, line_count = 0;
            bool transparent = false;
            Color color;
            int component = 0;
        };
        std::vector<ModelPartGL> model_parts;
        struct ModelComponentGL
        {
            std::string name;
            Box3 bounds;
            GLuint instance_vbo = 0;
            GLsizei instance_count = 0;
        };
        struct PlacedComponent
        {
            int component;
            float rows[12];
        };
        std::vector<ModelComponentGL> model_components;
        float model_units_per_metre = 1.0f;
        GLsizei instance_total = 0;
        uint64_t instance_upload_revision = UINT64_MAX;
        bool show_instances = true;
        float frame_far_plane = 0.0f;
        bool caps_dirty = true;
        uint64_t caps_scene_revision = UINT64_MAX;
        bool pick_initialized = false;
        std::vector<uint8_t> pick_buffer;
        float bg_r = 0.08f, bg_g = 0.08f, bg_b = 0.08f, bg_a = 1.0f;
        bool initialized = false;
        bool oit_initialized = false;
        bool suspended = true;
        Scene *scene = nullptr;
        Camera *camera = nullptr;
        std::chrono::high_resolution_clock::time_point last_render_time{};
        float accumulator = 0.0f;
        bool first_frame = true;
#ifdef _WIN32
        HDC hdc = nullptr;
        HGLRC hglrc = nullptr;
#endif
        ~Impl() { shutdown(); }
        bool init(uintptr_t window_handle);
        void shutdown();
        GLuint create_shader(const char *vs, const char *fs);
        void set_lighting_uniforms(GLuint shader);
        void upload_matrices(GLuint shader);
        void init_oit();
        void resize_oit(int w, int h);
        void init_pick();
        void resize_pick(int w, int h);
        int pick_at(int x, int y);
        void render();
        void clear_frame();
        void suspend();
        void resume();
        void set_plan_texture(
            const std::string &pixels_rgba,
            int width_px,
            int height_px,
            float page_width,
            float page_height,
            float plane_x,
            float plane_y,
            float plane_z,
            float opacity,
            bool visible,
            bool flip_u,
            bool flip_v);
        void clear_plan_texture();
        void set_plan_texture_visibility(bool visible);
        void set_plan_texture_opacity(float opacity);
        bool has_visible_plan_texture() const;
        void render_plan_texture();
        void render_opaque();
        void render_transparent();
        void render_pick_pass();
        void render_wireframe();
        void render_edges();
        void clear_caps();
        void ensure_caps();
        void draw_caps(bool transparent);
        void set_section_cut(int axis, bool enabled, float position);
        void set_instanced_model(const std::string &glb_bytes, float units_per_metre);
        void clear_instanced_model();
        void upload_instances();
        bool instances_drawable() const;
        void draw_instances(bool transparent);
        void draw_instance_edges(GLint color_location);
        Box3 instance_bounds() const;
        void place_components(const ModelInstance &instance, std::vector<PlacedComponent> &placed) const;
        glm::mat4 projection_matrix() const;
        void composite();
        void setup_quad();
        void resize(int w, int h);
    };
    Renderer::Renderer(uintptr_t native_window_handle)
        : pImpl(std::make_unique<Impl>())
    {
        pImpl->scene = &scene;
        pImpl->camera = &camera;
        pImpl->init(native_window_handle);
#ifdef _WIN32
        scene.attach_gl_context(pImpl->hdc, pImpl->hglrc);
#endif
    }
    Renderer::~Renderer() = default;
    bool Renderer::Impl::init(uintptr_t window_handle)
    {
        if (initialized)
            return true;
        native_window = window_handle;
#ifdef _WIN32
        HWND hwnd = reinterpret_cast<HWND>(window_handle);
        hdc = GetDC(hwnd);
        PIXELFORMATDESCRIPTOR pfd_temp = {};
        pfd_temp.nSize = sizeof(pfd_temp);
        pfd_temp.nVersion = 1;
        pfd_temp.dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER;
        pfd_temp.iPixelType = PFD_TYPE_RGBA;
        pfd_temp.cColorBits = 32;
        pfd_temp.cDepthBits = 24;
        pfd_temp.cStencilBits = 8;
        int temp_pf = ChoosePixelFormat(hdc, &pfd_temp);
        SetPixelFormat(hdc, temp_pf, &pfd_temp);
        HGLRC temp_ctx = wglCreateContext(hdc);
        wglMakeCurrent(hdc, temp_ctx);
        gladLoadGL();
        typedef BOOL(WINAPI * PFNWGLCHOOSEPIXELFORMATARBPROC)(HDC, const int *, const FLOAT *, UINT, int *, UINT *);
        typedef HGLRC(WINAPI * PFNWGLCREATECONTEXTATTRIBSARBPROC)(HDC, HGLRC, const int *);
        auto wglChoosePixelFormatARB = (PFNWGLCHOOSEPIXELFORMATARBPROC)wglGetProcAddress("wglChoosePixelFormatARB");
        auto wglCreateContextAttribsARB = (PFNWGLCREATECONTEXTATTRIBSARBPROC)wglGetProcAddress("wglCreateContextAttribsARB");
        HGLRC new_ctx = nullptr;
        if (wglChoosePixelFormatARB && wglCreateContextAttribsARB)
        {
            constexpr int WGL_DRAW_TO_WINDOW_ARB = 0x2001;
            constexpr int WGL_SUPPORT_OPENGL_ARB = 0x2010;
            constexpr int WGL_DOUBLE_BUFFER_ARB = 0x2011;
            constexpr int WGL_PIXEL_TYPE_ARB = 0x2013;
            constexpr int WGL_TYPE_RGBA_ARB = 0x202B;
            constexpr int WGL_COLOR_BITS_ARB = 0x2014;
            constexpr int WGL_DEPTH_BITS_ARB = 0x2022;
            constexpr int WGL_STENCIL_BITS_ARB = 0x2023;
            constexpr int WGL_SAMPLE_BUFFERS_ARB = 0x2041;
            constexpr int WGL_SAMPLES_ARB = 0x2042;
            const int desired_samples[] = {16, 8, 4, 2};
            for (int samples : desired_samples)
            {
                int attribs[] = {
                    WGL_DRAW_TO_WINDOW_ARB, 1,
                    WGL_SUPPORT_OPENGL_ARB, 1,
                    WGL_DOUBLE_BUFFER_ARB, 1,
                    WGL_PIXEL_TYPE_ARB, WGL_TYPE_RGBA_ARB,
                    WGL_COLOR_BITS_ARB, 32,
                    WGL_DEPTH_BITS_ARB, 24,
                    WGL_STENCIL_BITS_ARB, 8,
                    WGL_SAMPLE_BUFFERS_ARB, 1,
                    WGL_SAMPLES_ARB, samples,
                    0};
                int format;
                UINT num_formats;
                if (wglChoosePixelFormatARB(hdc, attribs, nullptr, 1, &format, &num_formats) && num_formats > 0)
                {
                    this->samples = samples;
                    wglMakeCurrent(nullptr, nullptr);
                    wglDeleteContext(temp_ctx);
                    temp_ctx = nullptr;
                    PIXELFORMATDESCRIPTOR pfd;
                    DescribePixelFormat(hdc, format, sizeof(pfd), &pfd);
                    SetPixelFormat(hdc, format, &pfd);
                    constexpr int WGL_CONTEXT_MAJOR_VERSION_ARB = 0x2091;
                    constexpr int WGL_CONTEXT_MINOR_VERSION_ARB = 0x2092;
                    constexpr int WGL_CONTEXT_PROFILE_MASK_ARB = 0x9126;
                    constexpr int WGL_CONTEXT_CORE_PROFILE_BIT_ARB = 0x00000001;
                    int context_attribs[] = {
                        WGL_CONTEXT_MAJOR_VERSION_ARB, 3,
                        WGL_CONTEXT_MINOR_VERSION_ARB, 3,
                        WGL_CONTEXT_PROFILE_MASK_ARB, WGL_CONTEXT_CORE_PROFILE_BIT_ARB,
                        0};
                    new_ctx = wglCreateContextAttribsARB(hdc, nullptr, context_attribs);
                    break;
                }
            }
        }
        if (new_ctx)
        {
            hglrc = new_ctx;
        }
        else
        {
            hglrc = temp_ctx;
        }
        wglMakeCurrent(hdc, hglrc);
        typedef BOOL(WINAPI * PFNWGLSWAPINTERVALEXTPROC)(int interval);
        auto wglSwapIntervalEXT = (PFNWGLSWAPINTERVALEXTPROC)wglGetProcAddress("wglSwapIntervalEXT");
        if (wglSwapIntervalEXT)
        {
            wglSwapIntervalEXT(1);
        }
#endif
        if (!gladLoadGL())
            return false;
        glEnable(GL_MULTISAMPLE);
        glEnable(GL_LINE_SMOOTH);
        glHint(GL_LINE_SMOOTH_HINT, GL_NICEST);
        glHint(GL_PERSPECTIVE_CORRECTION_HINT, GL_NICEST);
        opaque_shader = create_shader(mesh_vertex_shader, opaque_fragment_shader);
        transparent_accum_shader = create_shader(mesh_vertex_shader, transparent_accum_fragment_shader);
        plan_texture_shader = create_shader(plan_texture_vertex_shader, plan_texture_fragment_shader);
        composite_shader = create_shader(quad_vertex_shader, composite_fragment_shader);
        set_lighting_uniforms(opaque_shader);
        set_lighting_uniforms(transparent_accum_shader);
        glEnable(GL_DEPTH_TEST);
        init_oit();
        init_pick();
        setup_quad();
        initialized = true;
        clear_frame();
        return true;
    }
    void Renderer::Impl::set_lighting_uniforms(GLuint shader)
    {
        glUseProgram(shader);
        glUniform1f(glGetUniformLocation(shader, "ambientIntensity"), 0.55f);
        glUniform3f(glGetUniformLocation(shader, "keyLightDir"), 500.0f, -500.0f, 500.0f);
        glUniform1f(glGetUniformLocation(shader, "keyLightIntensity"), 0.45f);
        glUniform3f(glGetUniformLocation(shader, "fillLightDir"), -500.0f, 500.0f, 500.0f);
        glUniform1f(glGetUniformLocation(shader, "fillLightIntensity"), 0.35f);
        glUniform3f(glGetUniformLocation(shader, "rimLightDir"), 0.0f, 500.0f, -500.0f);
        glUniform1f(glGetUniformLocation(shader, "rimLightIntensity"), 0.2f);
    }
    void Renderer::Impl::upload_matrices(GLuint shader)
    {
        glm::mat4 model(1.0f);
        glm::mat4 view;
        camera->get_view_matrix(glm::value_ptr(view));
        glm::mat4 projection = projection_matrix();
        glUniformMatrix4fv(glGetUniformLocation(shader, "model"), 1, GL_FALSE, glm::value_ptr(model));
        glUniformMatrix4fv(glGetUniformLocation(shader, "view"), 1, GL_FALSE, glm::value_ptr(view));
        glUniformMatrix4fv(glGetUniformLocation(shader, "projection"), 1, GL_FALSE, glm::value_ptr(projection));
        GLint cutLoc = glGetUniformLocation(shader, "sectionCut");
        if (cutLoc >= 0)
            glUniform4f(cutLoc, cut_enabled[1] ? 1.0f : 0.0f, cut_position[1], cut_enabled[0] ? 1.0f : 0.0f,
                        cut_position[0]);
    }
    void Renderer::Impl::clear_caps()
    {
        for (auto &cap : caps)
        {
            if (cap.vao)
                glDeleteVertexArrays(1, &cap.vao);
            if (cap.line_vao)
                glDeleteVertexArrays(1, &cap.line_vao);
            if (cap.vbo)
                glDeleteBuffers(1, &cap.vbo);
            if (cap.ebo)
                glDeleteBuffers(1, &cap.ebo);
            if (cap.line_ebo)
                glDeleteBuffers(1, &cap.line_ebo);
        }
        caps.clear();
    }
    void Renderer::Impl::ensure_caps()
    {
        if (!caps_dirty && caps_scene_revision == scene->revision())
            return;
        clear_caps();
        caps_dirty = false;
        caps_scene_revision = scene->revision();
        if (!cut_enabled[0] && !cut_enabled[1])
            return;
        const float inset = 0.01f;
        for (const auto &mesh : scene->get_meshes())
        {
            std::vector<CapVertex> verts;
            std::vector<uint32_t> tris, lines;
            for (int axis = 0; axis < 2; ++axis)
                if (cut_enabled[axis])
                    append_section_cap(mesh, axis, cut_position[axis] - inset, verts, tris, lines);
            if (tris.empty())
                continue;
            CapMesh cap;
            cap.mesh_index = mesh.mesh_index;
            cap.transparent = mesh.transparent;
            cap.color = mesh.color;
            cap.index_count = (GLsizei)tris.size();
            cap.line_count = (GLsizei)lines.size();
            glGenVertexArrays(1, &cap.vao);
            glGenBuffers(1, &cap.vbo);
            glGenBuffers(1, &cap.ebo);
            glBindVertexArray(cap.vao);
            glBindBuffer(GL_ARRAY_BUFFER, cap.vbo);
            glBufferData(GL_ARRAY_BUFFER, verts.size() * sizeof(CapVertex), verts.data(), GL_STATIC_DRAW);
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, cap.ebo);
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, tris.size() * sizeof(uint32_t), tris.data(), GL_STATIC_DRAW);
            glEnableVertexAttribArray(0);
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(CapVertex), 0);
            glEnableVertexAttribArray(1);
            glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(CapVertex), (void *)offsetof(CapVertex, nx));
            glEnableVertexAttribArray(2);
            glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, sizeof(CapVertex), (void *)offsetof(CapVertex, r));
            if (!lines.empty())
            {
                glGenVertexArrays(1, &cap.line_vao);
                glGenBuffers(1, &cap.line_ebo);
                glBindVertexArray(cap.line_vao);
                glBindBuffer(GL_ARRAY_BUFFER, cap.vbo);
                glEnableVertexAttribArray(0);
                glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(CapVertex), 0);
                glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, cap.line_ebo);
                glBufferData(GL_ELEMENT_ARRAY_BUFFER, lines.size() * sizeof(uint32_t), lines.data(), GL_STATIC_DRAW);
            }
            glBindVertexArray(0);
            caps.push_back(cap);
        }
    }
    void Renderer::Impl::draw_caps(bool transparent)
    {
        for (const auto &cap : caps)
        {
            if (cap.transparent != transparent)
                continue;
            glBindVertexArray(cap.vao);
            glDrawElements(GL_TRIANGLES, cap.index_count, GL_UNSIGNED_INT, 0);
        }
        glBindVertexArray(0);
    }
    void Renderer::Impl::set_section_cut(int axis, bool enabled, float position)
    {
        if (axis < 0 || axis > 1)
            throw std::invalid_argument("section cut axis must be 0 (x) or 1 (y)");
        if (!std::isfinite(position))
            enabled = false;
        if (cut_enabled[axis] == enabled && (!enabled || cut_position[axis] == position))
            return;
        cut_enabled[axis] = enabled;
        cut_position[axis] = enabled ? position : 0.0f;
        caps_dirty = true;
    }

    glm::mat4 Renderer::Impl::projection_matrix() const
    {
        glm::mat4 projection;
        camera->get_projection_matrix(glm::value_ptr(projection));
        if (frame_far_plane > camera->far_plane)
            projection = glm::perspective(glm::radians(camera->fov), camera->aspect_ratio, camera->near_plane,
                                          frame_far_plane);
        return projection;
    }
    void Renderer::Impl::clear_instanced_model()
    {
        for (auto &part : model_parts)
        {
            if (part.vao)
                glDeleteVertexArrays(1, &part.vao);
            if (part.line_vao)
                glDeleteVertexArrays(1, &part.line_vao);
            if (part.vbo)
                glDeleteBuffers(1, &part.vbo);
            if (part.ebo)
                glDeleteBuffers(1, &part.ebo);
            if (part.line_ebo)
                glDeleteBuffers(1, &part.line_ebo);
        }
        model_parts.clear();
        for (auto &component : model_components)
            if (component.instance_vbo)
                glDeleteBuffers(1, &component.instance_vbo);
        model_components.clear();
        instance_total = 0;
        instance_upload_revision = UINT64_MAX;
    }
    void Renderer::Impl::set_instanced_model(const std::string &glb_bytes, float units_per_metre)
    {
        ModelParts parsed = parse_instanced_model(glb_bytes, units_per_metre);
        if (!initialized)
            return;
#ifdef _WIN32
        ContextGuard guard(hdc, hglrc);
#endif
        clear_instanced_model();
        model_units_per_metre = units_per_metre;
        const GLsizei instance_stride = 16 * sizeof(float);
        auto bind_instance_attributes = [&](GLuint instance_vbo)
        {
            glBindBuffer(GL_ARRAY_BUFFER, instance_vbo);
            for (GLuint slot = 0; slot < 4; ++slot)
            {
                glEnableVertexAttribArray(3 + slot);
                glVertexAttribPointer(3 + slot, 4, GL_FLOAT, GL_FALSE, instance_stride,
                                      (void *)(slot * 4 * sizeof(float)));
                glVertexAttribDivisor(3 + slot, 1);
            }
        };
        struct Vertex
        {
            float x, y, z, nx, ny, nz, r, g, b, a;
        };
        std::vector<std::pair<int, const ModelPart *>> component_parts;
        for (size_t component_index = 0; component_index < parsed.components.size(); ++component_index)
        {
            ModelComponentGL component;
            component.name = parsed.components[component_index].name;
            component.bounds = parsed.components[component_index].bounds;
            glGenBuffers(1, &component.instance_vbo);
            model_components.push_back(std::move(component));
            for (const auto &part : parsed.components[component_index].parts)
                component_parts.emplace_back((int)component_index, &part);
        }
        for (const auto &component_part : component_parts)
        {
            const ModelPart &part = *component_part.second;
            ModelPartGL gl_part;
            gl_part.component = component_part.first;
            gl_part.color = part.color;
            gl_part.transparent = part.color.a < 0.99f;
            gl_part.index_count = (GLsizei)part.indices.size();
            std::vector<Vertex> verts;
            verts.reserve(part.positions.size());
            for (size_t i = 0; i < part.positions.size(); ++i)
            {
                const Vec3 &p = part.positions[i];
                const Vec3 &n = part.normals[i];
                verts.push_back({p.x, p.y, p.z, n.x, n.y, n.z, part.color.r, part.color.g, part.color.b, part.color.a});
            }
            glGenVertexArrays(1, &gl_part.vao);
            glGenBuffers(1, &gl_part.vbo);
            glGenBuffers(1, &gl_part.ebo);
            glBindVertexArray(gl_part.vao);
            glBindBuffer(GL_ARRAY_BUFFER, gl_part.vbo);
            glBufferData(GL_ARRAY_BUFFER, verts.size() * sizeof(Vertex), verts.data(), GL_STATIC_DRAW);
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, gl_part.ebo);
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, part.indices.size() * sizeof(uint32_t), part.indices.data(),
                         GL_STATIC_DRAW);
            glEnableVertexAttribArray(0);
            glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex), 0);
            glEnableVertexAttribArray(1);
            glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex), (void *)offsetof(Vertex, nx));
            glEnableVertexAttribArray(2);
            glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, sizeof(Vertex), (void *)offsetof(Vertex, r));
            const GLuint component_vbo = model_components[(size_t)gl_part.component].instance_vbo;
            bind_instance_attributes(component_vbo);
            std::vector<uint32_t> lines =
                parsed.has_baked_lines ? part.lines : feature_edge_indices(part.positions, part.indices);
            if (!lines.empty())
            {
                gl_part.line_count = (GLsizei)lines.size();
                glGenVertexArrays(1, &gl_part.line_vao);
                glGenBuffers(1, &gl_part.line_ebo);
                glBindVertexArray(gl_part.line_vao);
                glBindBuffer(GL_ARRAY_BUFFER, gl_part.vbo);
                glEnableVertexAttribArray(0);
                glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(Vertex), 0);
                bind_instance_attributes(component_vbo);
                glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, gl_part.line_ebo);
                glBufferData(GL_ELEMENT_ARRAY_BUFFER, lines.size() * sizeof(uint32_t), lines.data(), GL_STATIC_DRAW);
            }
            glBindVertexArray(0);
            model_parts.push_back(gl_part);
        }
        glBindBuffer(GL_ARRAY_BUFFER, 0);
    }
    void Renderer::Impl::place_components(const ModelInstance &instance, std::vector<PlacedComponent> &placed) const
    {
        const double c = std::cos((double)instance.rotation), s = std::sin((double)instance.rotation);
        const double origin[3] = {instance.position.x, instance.position.y, instance.position.z};
        auto place = [&](int component, const double local[12])
        {
            PlacedComponent item;
            item.component = component;
            for (int k = 0; k < 4; ++k)
            {
                item.rows[k] = (float)(c * local[k] - s * local[4 + k] + (k == 3 ? origin[0] : 0.0));
                item.rows[4 + k] = (float)(s * local[k] + c * local[4 + k] + (k == 3 ? origin[1] : 0.0));
                item.rows[8 + k] = (float)(local[8 + k] + (k == 3 ? origin[2] : 0.0));
            }
            placed.push_back(item);
        };
        if (instance.layout < 0)
        {
            const double identity[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};
            for (size_t i = 0; i < model_components.size(); ++i)
                place((int)i, identity);
            return;
        }
        const auto &layouts = scene->model_layouts();
        if ((size_t)instance.layout >= layouts.size())
            return;
        const double units = model_units_per_metre;
        for (const auto &item : layouts[(size_t)instance.layout].items)
        {
            int component = -1;
            for (size_t i = 0; i < model_components.size(); ++i)
                if (model_components[i].name == item.component)
                {
                    component = (int)i;
                    break;
                }
            if (component < 0)
                continue;
            const float *m = item.matrix;
            const double local[12] = {m[0], -m[2], -m[1], -units * m[3],
                                      -m[8], m[10], m[9], units * m[11],
                                      -m[4], m[6], m[5], units * m[7]};
            place(component, local);
        }
    }
    void Renderer::Impl::upload_instances()
    {
        if (model_components.empty())
        {
            instance_total = 0;
            return;
        }
        if (instance_upload_revision == scene->instance_revision())
            return;
        instance_upload_revision = scene->instance_revision();
        std::vector<std::vector<float>> data(model_components.size());
        std::vector<PlacedComponent> placed;
        for (const auto &instance : scene->model_instances())
        {
            placed.clear();
            place_components(instance, placed);
            for (const auto &item : placed)
            {
                std::vector<float> &rows = data[(size_t)item.component];
                rows.insert(rows.end(), item.rows, item.rows + 12);
                rows.insert(rows.end(), {instance.tint.r, instance.tint.g, instance.tint.b, instance.tint.a});
            }
        }
        instance_total = 0;
        for (size_t i = 0; i < model_components.size(); ++i)
        {
            glBindBuffer(GL_ARRAY_BUFFER, model_components[i].instance_vbo);
            glBufferData(GL_ARRAY_BUFFER, data[i].size() * sizeof(float), data[i].empty() ? nullptr : data[i].data(),
                         GL_DYNAMIC_DRAW);
            model_components[i].instance_count = (GLsizei)(data[i].size() / 16);
            instance_total += model_components[i].instance_count;
        }
        glBindBuffer(GL_ARRAY_BUFFER, 0);
    }
    bool Renderer::Impl::instances_drawable() const
    {
        return show_instances && instance_total > 0 && !model_parts.empty();
    }
    void Renderer::Impl::draw_instances(bool transparent)
    {
        if (!instances_drawable())
            return;
        for (const auto &part : model_parts)
        {
            const GLsizei instance_count = model_components[(size_t)part.component].instance_count;
            if (part.transparent != transparent || instance_count == 0)
                continue;
            glBindVertexArray(part.vao);
            glDrawElementsInstanced(GL_TRIANGLES, part.index_count, GL_UNSIGNED_INT, 0, instance_count);
        }
        glBindVertexArray(0);
        reset_instance_attributes();
    }
    void Renderer::Impl::draw_instance_edges(GLint color_location)
    {
        if (!instances_drawable())
            return;
        const float edge_scale = 0.45f;
        GLint tint_scale_location = glGetUniformLocation(flat_color_shader_prog, "u_tintScale");
        glUniform1f(tint_scale_location, edge_scale);
        for (const auto &part : model_parts)
        {
            const GLsizei instance_count = model_components[(size_t)part.component].instance_count;
            if (!part.line_vao || instance_count == 0)
                continue;
            float color[4] = {part.color.r * edge_scale, part.color.g * edge_scale, part.color.b * edge_scale, 1.0f};
            glUniform4fv(color_location, 1, color);
            glBindVertexArray(part.line_vao);
            glDrawElementsInstanced(GL_LINES, part.line_count, GL_UNSIGNED_INT, 0, instance_count);
        }
        glUniform1f(tint_scale_location, 0.0f);
        glBindVertexArray(0);
        reset_instance_attributes();
    }
    Box3 Renderer::Impl::instance_bounds() const
    {
        Box3 bounds;
        if (!show_instances || model_parts.empty())
            return bounds;
        std::vector<PlacedComponent> placed;
        for (const auto &instance : scene->model_instances())
        {
            placed.clear();
            place_components(instance, placed);
            for (const auto &item : placed)
            {
                const Box3 &local = model_components[(size_t)item.component].bounds;
                if (local.is_empty())
                    continue;
                const float *m = item.rows;
                for (int corner = 0; corner < 8; ++corner)
                {
                    float x = (corner & 1) ? local.max.x : local.min.x;
                    float y = (corner & 2) ? local.max.y : local.min.y;
                    float z = (corner & 4) ? local.max.z : local.min.z;
                    bounds.expand(Vec3(m[0] * x + m[1] * y + m[2] * z + m[3], m[4] * x + m[5] * y + m[6] * z + m[7],
                                       m[8] * x + m[9] * y + m[10] * z + m[11]));
                }
            }
        }
        return bounds;
    }

    void Renderer::Impl::shutdown()
    {
        if (!initialized)
            return;
        {
#ifdef _WIN32
            ContextGuard guard(hdc, hglrc);
#endif
            scene->clear();
            clear_caps();
            clear_instanced_model();
            clear_plan_texture();
            if (opaque_shader)
                glDeleteProgram(opaque_shader);
            if (transparent_accum_shader)
                glDeleteProgram(transparent_accum_shader);
            if (plan_texture_shader)
                glDeleteProgram(plan_texture_shader);
            if (composite_shader)
                glDeleteProgram(composite_shader);
            if (pick_shader_prog)
                glDeleteProgram(pick_shader_prog);
            if (flat_color_shader_prog)
                glDeleteProgram(flat_color_shader_prog);
            if (selection_post_shader_prog)
                glDeleteProgram(selection_post_shader_prog);
            if (accum_fbo)
                glDeleteFramebuffers(1, &accum_fbo);
            if (accum_texture)
                glDeleteTextures(1, &accum_texture);
            if (revealage_texture)
                glDeleteTextures(1, &revealage_texture);
            if (opaque_fbo)
                glDeleteFramebuffers(1, &opaque_fbo);
            if (opaque_texture)
                glDeleteTextures(1, &opaque_texture);
            if (depth_texture)
                glDeleteTextures(1, &depth_texture);
            if (opaque_ms_fbo)
                glDeleteFramebuffers(1, &opaque_ms_fbo);
            if (opaque_ms_color)
                glDeleteTextures(1, &opaque_ms_color);
            if (opaque_ms_depth)
                glDeleteRenderbuffers(1, &opaque_ms_depth);
            if (scene_fbo)
                glDeleteFramebuffers(1, &scene_fbo);
            if (scene_texture)
                glDeleteTextures(1, &scene_texture);
            if (sel_mask_fbo)
                glDeleteFramebuffers(1, &sel_mask_fbo);
            if (sel_mask_texture)
                glDeleteTextures(1, &sel_mask_texture);
            if (pick_fbo)
                glDeleteFramebuffers(1, &pick_fbo);
            if (pick_color)
                glDeleteTextures(1, &pick_color);
            if (pick_depth_rb)
                glDeleteRenderbuffers(1, &pick_depth_rb);
            if (quad_vao)
                glDeleteVertexArrays(1, &quad_vao);
            if (quad_vbo)
                glDeleteBuffers(1, &quad_vbo);
        }
#ifdef _WIN32
        if (hglrc)
        {
            wglMakeCurrent(nullptr, nullptr);
            wglDeleteContext(hglrc);
            hglrc = nullptr;
        }
        if (hdc)
        {
            ReleaseDC(reinterpret_cast<HWND>(native_window), hdc);
            hdc = nullptr;
        }
#endif
        initialized = false;
    }
    GLuint Renderer::Impl::create_shader(const char *vs, const char *fs)
    {
        auto compile = [](GLenum type, const char *source) -> GLuint
        {
            GLuint id = glCreateShader(type);
            glShaderSource(id, 1, &source, nullptr);
            glCompileShader(id);
            GLint success;
            glGetShaderiv(id, GL_COMPILE_STATUS, &success);
            if (!success)
            {
                char log[512];
                glGetShaderInfoLog(id, sizeof(log), nullptr, log);
                glDeleteShader(id);
                return 0;
            }
            return id;
        };
        GLuint vs_id = compile(GL_VERTEX_SHADER, vs);
        GLuint fs_id = compile(GL_FRAGMENT_SHADER, fs);
        if (!vs_id || !fs_id)
        {
            if (vs_id)
                glDeleteShader(vs_id);
            if (fs_id)
                glDeleteShader(fs_id);
            return 0;
        }
        GLuint prog = glCreateProgram();
        glAttachShader(prog, vs_id);
        glAttachShader(prog, fs_id);
        glLinkProgram(prog);
        glDeleteShader(vs_id);
        glDeleteShader(fs_id);
        GLint success;
        glGetProgramiv(prog, GL_LINK_STATUS, &success);
        if (!success)
        {
            char log[512];
            glGetProgramInfoLog(prog, sizeof(log), nullptr, log);
            glDeleteProgram(prog);
            return 0;
        }
        return prog;
    }
    void Renderer::Impl::init_oit()
    {
        int msaa_samples = (samples >= 4) ? 4 : ((samples >= 2) ? 2 : 1);
        glGenFramebuffers(1, &accum_fbo);
        glBindFramebuffer(GL_FRAMEBUFFER, accum_fbo);
        glGenTextures(1, &accum_texture);
        glBindTexture(GL_TEXTURE_2D, accum_texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, width, height, 0, GL_RGBA, GL_FLOAT, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, accum_texture, 0);
        glGenTextures(1, &revealage_texture);
        glBindTexture(GL_TEXTURE_2D, revealage_texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, width, height, 0, GL_RED, GL_UNSIGNED_BYTE, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1, GL_TEXTURE_2D, revealage_texture, 0);
        glGenTextures(1, &depth_texture);
        glBindTexture(GL_TEXTURE_2D, depth_texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, width, height, 0, GL_DEPTH_COMPONENT, GL_FLOAT, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, depth_texture, 0);
        GLenum accum_draw_buffers[] = {GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1};
        glDrawBuffers(2, accum_draw_buffers);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glGenFramebuffers(1, &opaque_fbo);
        glBindFramebuffer(GL_FRAMEBUFFER, opaque_fbo);
        glGenTextures(1, &opaque_texture);
        glBindTexture(GL_TEXTURE_2D, opaque_texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, opaque_texture, 0);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, depth_texture, 0);
        glDrawBuffer(GL_COLOR_ATTACHMENT0);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        if (msaa_samples > 1)
        {
            glGenFramebuffers(1, &opaque_ms_fbo);
            glBindFramebuffer(GL_FRAMEBUFFER, opaque_ms_fbo);
            glGenTextures(1, &opaque_ms_color);
            glBindTexture(GL_TEXTURE_2D_MULTISAMPLE, opaque_ms_color);
            glTexImage2DMultisample(GL_TEXTURE_2D_MULTISAMPLE, msaa_samples, GL_RGBA8, width, height, GL_TRUE);
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D_MULTISAMPLE, opaque_ms_color, 0);
            glGenRenderbuffers(1, &opaque_ms_depth);
            glBindRenderbuffer(GL_RENDERBUFFER, opaque_ms_depth);
            glRenderbufferStorageMultisample(GL_RENDERBUFFER, msaa_samples, GL_DEPTH_COMPONENT24, width, height);
            glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, opaque_ms_depth);
            glDrawBuffer(GL_COLOR_ATTACHMENT0);
            glBindFramebuffer(GL_FRAMEBUFFER, 0);
        }
        oit_initialized = true;
    }
    void Renderer::Impl::resize_oit(int w, int h)
    {
        if (!oit_initialized)
            return;
        int msaa_samples = (samples >= 4) ? 4 : ((samples >= 2) ? 2 : 1);
        glBindTexture(GL_TEXTURE_2D, accum_texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0, GL_RGBA, GL_FLOAT, nullptr);
        glBindTexture(GL_TEXTURE_2D, revealage_texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, w, h, 0, GL_RED, GL_UNSIGNED_BYTE, nullptr);
        glBindTexture(GL_TEXTURE_2D, depth_texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, w, h, 0, GL_DEPTH_COMPONENT, GL_FLOAT, nullptr);
        glBindTexture(GL_TEXTURE_2D, opaque_texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        if (msaa_samples > 1 && opaque_ms_fbo)
        {
            glBindTexture(GL_TEXTURE_2D_MULTISAMPLE, opaque_ms_color);
            glTexImage2DMultisample(GL_TEXTURE_2D_MULTISAMPLE, msaa_samples, GL_RGBA8, w, h, GL_TRUE);
            glBindRenderbuffer(GL_RENDERBUFFER, opaque_ms_depth);
            glRenderbufferStorageMultisample(GL_RENDERBUFFER, msaa_samples, GL_DEPTH_COMPONENT24, w, h);
        }
    }
    void Renderer::Impl::init_pick()
    {
        if (pick_initialized)
            return;
        pick_shader_prog = create_shader(mesh_vertex_shader, pick_fragment_shader);
        flat_color_shader_prog = create_shader(mesh_vertex_shader, flat_color_fragment_shader);
        selection_post_shader_prog = create_shader(quad_vertex_shader, selection_post_fragment_shader);
        glGenFramebuffers(1, &scene_fbo);
        glGenTextures(1, &scene_texture);
        glBindTexture(GL_TEXTURE_2D, scene_texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glBindFramebuffer(GL_FRAMEBUFFER, scene_fbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, scene_texture, 0);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glGenFramebuffers(1, &sel_mask_fbo);
        glGenTextures(1, &sel_mask_texture);
        glBindTexture(GL_TEXTURE_2D, sel_mask_texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, width, height, 0, GL_RED, GL_UNSIGNED_BYTE, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glBindFramebuffer(GL_FRAMEBUFFER, sel_mask_fbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, sel_mask_texture, 0);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glGenFramebuffers(1, &pick_fbo);
        glGenTextures(1, &pick_color);
        glGenRenderbuffers(1, &pick_depth_rb);
        glBindTexture(GL_TEXTURE_2D, pick_color);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glBindRenderbuffer(GL_RENDERBUFFER, pick_depth_rb);
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, width, height);
        glBindFramebuffer(GL_FRAMEBUFFER, pick_fbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, pick_color, 0);
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, pick_depth_rb);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        pick_initialized = true;
    }
    void Renderer::Impl::resize_pick(int w, int h)
    {
        if (!pick_initialized)
            return;
        glBindTexture(GL_TEXTURE_2D, pick_color);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        glBindRenderbuffer(GL_RENDERBUFFER, pick_depth_rb);
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, w, h);
        glBindTexture(GL_TEXTURE_2D, scene_texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        glBindTexture(GL_TEXTURE_2D, sel_mask_texture);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, w, h, 0, GL_RED, GL_UNSIGNED_BYTE, nullptr);
    }
    void Renderer::Impl::render_pick_pass()
    {
        if (!pick_initialized || !pick_shader_prog)
            return;
        while (glGetError() != GL_NO_ERROR)
        {
        }
        glBindFramebuffer(GL_FRAMEBUFFER, pick_fbo);
        glViewport(0, 0, width, height);
        glClearColor(0, 0, 0, 0);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glEnable(GL_DEPTH_TEST);
        glDepthFunc(GL_LESS);
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glUseProgram(pick_shader_prog);
        upload_matrices(pick_shader_prog);
        GLint loc = glGetUniformLocation(pick_shader_prog, "u_meshId");
        for (auto &m : scene->get_meshes())
        {
            if (!m.vao || m.index_count == 0)
                continue;
            int encoded = m.mesh_index + 1;
            float mid[4] = {
                ((encoded) & 0xFF) / 255.0f,
                ((encoded >> 8) & 0xFF) / 255.0f,
                0.0f, 1.0f};
            glUniform4fv(loc, 1, mid);
            glBindVertexArray(m.vao);
            glDrawElements(GL_TRIANGLES, (GLsizei)m.index_count, GL_UNSIGNED_INT, 0);
        }
        for (const auto &cap : caps)
        {
            int encoded = cap.mesh_index + 1;
            float mid[4] = {
                ((encoded) & 0xFF) / 255.0f,
                ((encoded >> 8) & 0xFF) / 255.0f,
                0.0f, 1.0f};
            glUniform4fv(loc, 1, mid);
            glBindVertexArray(cap.vao);
            glDrawElements(GL_TRIANGLES, cap.index_count, GL_UNSIGNED_INT, 0);
        }
        float background_id[4] = {0.0f, 0.0f, 0.0f, 1.0f};
        glUniform4fv(loc, 1, background_id);
        draw_instances(false);
        draw_instances(true);
        glBindVertexArray(0);
        pick_buffer.resize((size_t)width * height * 4);
        glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, pick_buffer.data());
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
    }
    int Renderer::Impl::pick_at(int x, int y)
    {
        if (!pick_initialized)
            return -1;
        if (x < 0 || x >= width || y < 0 || y >= height)
            return -1;
        if (pick_buffer.empty())
            return -1;
        int flipped_y = height - 1 - y;
        size_t offset = ((size_t)flipped_y * width + x) * 4;
        if (offset + 1 >= pick_buffer.size())
            return -1;
        int meshIdx = (int)pick_buffer[offset] | ((int)pick_buffer[offset + 1] << 8);
        return (meshIdx == 0) ? -1 : meshIdx - 1;
    }
    void Renderer::Impl::render_wireframe()
    {
        if (scene->get_selected().empty())
            return;
        if (!flat_color_shader_prog)
            return;
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glDisable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);
        glDisable(GL_BLEND);
        glUseProgram(flat_color_shader_prog);
        upload_matrices(flat_color_shader_prog);
        GLint colorLoc = glGetUniformLocation(flat_color_shader_prog, "u_color");
        float yellow[4] = {1.0f, 0.95f, 0.0f, 1.0f};
        glUniform4fv(colorLoc, 1, yellow);
        for (auto &m : scene->get_meshes())
        {
            if (!scene->is_selected(m.mesh_index))
                continue;
            if (m.line_count == 0 || m.line_vao == 0)
                continue;
            glBindVertexArray(m.line_vao);
            glDrawElements(GL_LINES, (GLsizei)m.line_count, GL_UNSIGNED_INT, 0);
        }
        for (const auto &cap : caps)
        {
            if (!scene->is_selected(cap.mesh_index) || !cap.line_vao)
                continue;
            glBindVertexArray(cap.line_vao);
            glDrawElements(GL_LINES, cap.line_count, GL_UNSIGNED_INT, 0);
        }
        glBindVertexArray(0);
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
    }
    void Renderer::Impl::render_edges()
    {
        if (!flat_color_shader_prog)
            return;
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);
        glDisable(GL_BLEND);
        glUseProgram(flat_color_shader_prog);
        upload_matrices(flat_color_shader_prog);
        GLint colorLoc = glGetUniformLocation(flat_color_shader_prog, "u_color");
        const float edge_scale = 0.45f;
        for (auto &m : scene->get_meshes())
        {
            if (m.line_count == 0 || m.line_vao == 0)
                continue;
            float color[4] = {m.color.r * edge_scale, m.color.g * edge_scale, m.color.b * edge_scale, 1.0f};
            glUniform4fv(colorLoc, 1, color);
            glBindVertexArray(m.line_vao);
            glDrawElements(GL_LINES, (GLsizei)m.line_count, GL_UNSIGNED_INT, 0);
        }
        for (const auto &cap : caps)
        {
            if (!cap.line_vao)
                continue;
            float color[4] = {cap.color.r * edge_scale, cap.color.g * edge_scale, cap.color.b * edge_scale, 1.0f};
            glUniform4fv(colorLoc, 1, color);
            glBindVertexArray(cap.line_vao);
            glDrawElements(GL_LINES, cap.line_count, GL_UNSIGNED_INT, 0);
        }
        glBindVertexArray(0);
        draw_instance_edges(colorLoc);
        glDepthMask(GL_TRUE);
    }
    void Renderer::Impl::setup_quad()
    {
        float quad_vertices[] = {
            -1.0f, 1.0f, 0.0f, 1.0f,
            -1.0f, -1.0f, 0.0f, 0.0f,
            1.0f, -1.0f, 1.0f, 0.0f,
            -1.0f, 1.0f, 0.0f, 1.0f,
            1.0f, -1.0f, 1.0f, 0.0f,
            1.0f, 1.0f, 1.0f, 1.0f};
        glGenVertexArrays(1, &quad_vao);
        glGenBuffers(1, &quad_vbo);
        glBindVertexArray(quad_vao);
        glBindBuffer(GL_ARRAY_BUFFER, quad_vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(quad_vertices), quad_vertices, GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(float), (void *)0);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 4 * sizeof(float), (void *)(2 * sizeof(float)));
        glBindVertexArray(0);
    }
    void Renderer::Impl::set_plan_texture(
        const std::string &pixels_rgba,
        int width_px,
        int height_px,
        float page_width,
        float page_height,
        float plane_x,
        float plane_y,
        float plane_z,
        float opacity,
        bool visible,
        bool flip_u,
        bool flip_v)
    {
        plan_texture_ready = false;
        plan_texture_visible = false;
        if (width_px <= 0 || height_px <= 0)
            throw std::invalid_argument("Plan texture dimensions must be positive");
        if (page_width <= 0.0f || page_height <= 0.0f)
            throw std::invalid_argument("Plan texture page size must be positive");
        const size_t expected_size = static_cast<size_t>(width_px) * static_cast<size_t>(height_px) * 4;
        if (pixels_rgba.size() != expected_size)
            throw std::invalid_argument("Plan texture RGBA buffer length does not match dimensions");
        if (!initialized)
            return;
#ifdef _WIN32
        ContextGuard guard(hdc, hglrc);
#endif
        GLint max_texture_size = 0;
        glGetIntegerv(GL_MAX_TEXTURE_SIZE, &max_texture_size);
        if (max_texture_size > 0 && (width_px > max_texture_size || height_px > max_texture_size))
            throw std::invalid_argument("Plan texture exceeds GPU maximum texture size");
        if (!plan_texture)
            glGenTextures(1, &plan_texture);
        glBindTexture(GL_TEXTURE_2D, plan_texture);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
        glTexImage2D(
            GL_TEXTURE_2D,
            0,
            GL_RGBA8,
            width_px,
            height_px,
            0,
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            reinterpret_cast<const unsigned char *>(pixels_rgba.data()));
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        const float half_width = page_width * 0.5f;
        const float half_height = page_height * 0.5f;
        const float min_x = plane_x - half_width;
        const float max_x = plane_x + half_width;
        const float min_y = plane_y - half_height;
        const float max_y = plane_y + half_height;
        const float u_min = flip_u ? 1.0f : 0.0f;
        const float u_max = flip_u ? 0.0f : 1.0f;
        const float v_min = flip_v ? 1.0f : 0.0f;
        const float v_max = flip_v ? 0.0f : 1.0f;
        struct PlanVertex
        {
            float x, y, z, u, v;
        };
        PlanVertex vertices[] = {
            {min_x, min_y, plane_z, u_min, v_min},
            {max_x, min_y, plane_z, u_max, v_min},
            {max_x, max_y, plane_z, u_max, v_max},
            {min_x, max_y, plane_z, u_min, v_max},
        };
        uint32_t indices[] = {0, 1, 2, 2, 3, 0};
        if (!plan_vao)
            glGenVertexArrays(1, &plan_vao);
        if (!plan_vbo)
            glGenBuffers(1, &plan_vbo);
        if (!plan_ebo)
            glGenBuffers(1, &plan_ebo);
        glBindVertexArray(plan_vao);
        glBindBuffer(GL_ARRAY_BUFFER, plan_vbo);
        glBufferData(GL_ARRAY_BUFFER, sizeof(vertices), vertices, GL_STATIC_DRAW);
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, plan_ebo);
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, sizeof(indices), indices, GL_STATIC_DRAW);
        glEnableVertexAttribArray(0);
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, sizeof(PlanVertex), 0);
        glEnableVertexAttribArray(1);
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, sizeof(PlanVertex), (void *)offsetof(PlanVertex, u));
        glBindVertexArray(0);
        plan_texture_ready = true;
        plan_texture_visible = visible;
        plan_texture_opacity = glm::clamp(opacity, 0.0f, 1.0f);
    }
    void Renderer::Impl::clear_plan_texture()
    {
        if (!initialized)
            return;
#ifdef _WIN32
        ContextGuard guard(hdc, hglrc);
#endif
        if (plan_texture)
        {
            glDeleteTextures(1, &plan_texture);
            plan_texture = 0;
        }
        if (plan_vao)
        {
            glDeleteVertexArrays(1, &plan_vao);
            plan_vao = 0;
        }
        if (plan_vbo)
        {
            glDeleteBuffers(1, &plan_vbo);
            plan_vbo = 0;
        }
        if (plan_ebo)
        {
            glDeleteBuffers(1, &plan_ebo);
            plan_ebo = 0;
        }
        plan_texture_ready = false;
        plan_texture_visible = false;
        plan_texture_opacity = 1.0f;
    }
    void Renderer::Impl::set_plan_texture_visibility(bool visible)
    {
        plan_texture_visible = visible;
    }
    void Renderer::Impl::set_plan_texture_opacity(float opacity)
    {
        plan_texture_opacity = glm::clamp(opacity, 0.0f, 1.0f);
    }
    bool Renderer::Impl::has_visible_plan_texture() const
    {
        return plan_texture_ready && plan_texture_visible && plan_texture != 0 && plan_vao != 0;
    }
    void Renderer::Impl::render_plan_texture()
    {
        if (!has_visible_plan_texture() || !plan_texture_shader)
            return;
        glUseProgram(plan_texture_shader);
        glm::mat4 view;
        camera->get_view_matrix(glm::value_ptr(view));
        glm::mat4 projection = projection_matrix();
        glUniformMatrix4fv(glGetUniformLocation(plan_texture_shader, "view"), 1, GL_FALSE, glm::value_ptr(view));
        glUniformMatrix4fv(glGetUniformLocation(plan_texture_shader, "projection"), 1, GL_FALSE, glm::value_ptr(projection));
        glUniform1f(glGetUniformLocation(plan_texture_shader, "opacity"), plan_texture_opacity);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, plan_texture);
        glUniform1i(glGetUniformLocation(plan_texture_shader, "planTexture"), 0);
        glBindVertexArray(plan_vao);
        glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_INT, 0);
        glBindVertexArray(0);
    }
    void Renderer::Impl::render_opaque()
    {
        GLuint render_fbo = (opaque_ms_fbo != 0) ? opaque_ms_fbo : opaque_fbo;
        glBindFramebuffer(GL_FRAMEBUFFER, render_fbo);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
        render_plan_texture();
        glUseProgram(opaque_shader);
        upload_matrices(opaque_shader);
        if (show_edges)
        {
            glEnable(GL_POLYGON_OFFSET_FILL);
            glPolygonOffset(1.0f, 1.0f);
        }
        for (auto &m : scene->get_meshes())
        {
            if (m.transparent)
                continue;
            glBindVertexArray(m.vao);
            glDrawElements(GL_TRIANGLES, static_cast<GLsizei>(m.index_count), GL_UNSIGNED_INT, 0);
        }
        draw_caps(false);
        glBindVertexArray(0);
        draw_instances(false);
        if (show_edges)
        {
            glDisable(GL_POLYGON_OFFSET_FILL);
            render_edges();
        }
        if (opaque_ms_fbo != 0)
        {
            glBindFramebuffer(GL_READ_FRAMEBUFFER, opaque_ms_fbo);
            glReadBuffer(GL_COLOR_ATTACHMENT0);
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, opaque_fbo);
            glDrawBuffer(GL_COLOR_ATTACHMENT0);
            glBlitFramebuffer(0, 0, width, height, 0, 0, width, height, GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT, GL_NEAREST);
        }
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
    }
    void Renderer::Impl::render_transparent()
    {
        glBindFramebuffer(GL_FRAMEBUFFER, accum_fbo);
        GLenum accum_draw_bufs[2] = {GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1};
        glDrawBuffers(2, accum_draw_bufs);
        float zero4[] = {0.0f, 0.0f, 0.0f, 0.0f};
        float one1[] = {1.0f};
        glClearBufferfv(GL_COLOR, 0, zero4);
        glClearBufferfv(GL_COLOR, 1, one1);
        glDepthMask(GL_FALSE);
        glEnable(GL_DEPTH_TEST);
        glEnable(GL_BLEND);
        glBlendFunci(0, GL_ONE, GL_ONE);
        glBlendFunci(1, GL_ZERO, GL_ONE_MINUS_SRC_COLOR);
        glUseProgram(transparent_accum_shader);
        upload_matrices(transparent_accum_shader);
        for (auto &m : scene->get_meshes())
        {
            if (!m.transparent)
                continue;
            glBindVertexArray(m.vao);
            glDrawElements(GL_TRIANGLES, static_cast<GLsizei>(m.index_count), GL_UNSIGNED_INT, 0);
        }
        draw_caps(true);
        glBindVertexArray(0);
        draw_instances(true);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
    }
    void Renderer::Impl::composite()
    {
        glBindFramebuffer(GL_FRAMEBUFFER, scene_fbo);
        glClearColor(bg_r, bg_g, bg_b, bg_a);
        glClear(GL_COLOR_BUFFER_BIT);
        glDisable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);
        glUseProgram(composite_shader);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, accum_texture);
        glUniform1i(glGetUniformLocation(composite_shader, "accumTexture"), 0);
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, revealage_texture);
        glUniform1i(glGetUniformLocation(composite_shader, "revealageTexture"), 1);
        glActiveTexture(GL_TEXTURE2);
        glBindTexture(GL_TEXTURE_2D, opaque_texture);
        glUniform1i(glGetUniformLocation(composite_shader, "opaqueTexture"), 2);
        glBindVertexArray(quad_vao);
        glDrawArrays(GL_TRIANGLES, 0, 6);
        glBindVertexArray(0);
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
    }
    void Renderer::Impl::render()
    {
        if (!initialized)
            return;
#ifdef _WIN32
        wglMakeCurrent(hdc, hglrc);
#endif
        if (suspended)
        {
            clear_frame();
            return;
        }
        const float fixed_dt = 1.0f / 60.0f;
        auto current_time = std::chrono::high_resolution_clock::now();
        if (first_frame)
        {
            last_render_time = current_time;
            first_frame = false;
        }
        float frame_time = std::chrono::duration<float>(current_time - last_render_time).count();
        last_render_time = current_time;
        frame_time = std::min(frame_time, 0.1f);
        accumulator += frame_time;
        while (accumulator >= fixed_dt)
        {
            camera->update(fixed_dt);
            accumulator -= fixed_dt;
        }
        camera->interpolate(accumulator / fixed_dt);
        if (scene->empty() && !has_visible_plan_texture())
        {
            glBindFramebuffer(GL_FRAMEBUFFER, 0);
            glClearColor(bg_r, bg_g, bg_b, bg_a);
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
#ifdef _WIN32
            SwapBuffers(hdc);
#endif
            return;
        }
        reset_instance_attributes();
        upload_instances();
        frame_far_plane = 0.0f;
        if (instances_drawable())
        {
            Box3 extra = instance_bounds();
            glm::vec3 eye = camera->position.to_glm();
            float farthest = 0.0f;
            for (int corner = 0; corner < 8; ++corner)
            {
                glm::vec3 p((corner & 1) ? extra.max.x : extra.min.x, (corner & 2) ? extra.max.y : extra.min.y,
                            (corner & 4) ? extra.max.z : extra.min.z);
                farthest = std::max(farthest, glm::length(p - eye));
            }
            frame_far_plane = farthest * 1.25f;
        }
        ensure_caps();
        if (scene->empty())
            pick_buffer.clear();
        else
            render_pick_pass();
        render_opaque();
        render_transparent();
        composite();
        glBindFramebuffer(GL_FRAMEBUFFER, sel_mask_fbo);
        glViewport(0, 0, width, height);
        glClearColor(0, 0, 0, 0);
        glClear(GL_COLOR_BUFFER_BIT);
        if (!scene->get_selected().empty() && pick_shader_prog)
        {
            glDisable(GL_DEPTH_TEST);
            glDepthMask(GL_FALSE);
            glDisable(GL_BLEND);
            glUseProgram(pick_shader_prog);
            upload_matrices(pick_shader_prog);
            GLint loc = glGetUniformLocation(pick_shader_prog, "u_meshId");
            float white[4] = {1.0f, 1.0f, 1.0f, 1.0f};
            glUniform4fv(loc, 1, white);
            for (auto &m : scene->get_meshes())
            {
                if (!scene->is_selected(m.mesh_index))
                    continue;
                glBindVertexArray(m.vao);
                glDrawElements(GL_TRIANGLES, (GLsizei)m.index_count, GL_UNSIGNED_INT, 0);
            }
            for (const auto &cap : caps)
            {
                if (!scene->is_selected(cap.mesh_index))
                    continue;
                glBindVertexArray(cap.vao);
                glDrawElements(GL_TRIANGLES, cap.index_count, GL_UNSIGNED_INT, 0);
            }
            glBindVertexArray(0);
            glEnable(GL_DEPTH_TEST);
            glDepthMask(GL_TRUE);
        }
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glClearColor(bg_r, bg_g, bg_b, bg_a);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glDisable(GL_DEPTH_TEST);
        glDepthMask(GL_FALSE);
        glUseProgram(selection_post_shader_prog);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, scene_texture);
        glUniform1i(glGetUniformLocation(selection_post_shader_prog, "sceneTex"), 0);
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_2D, sel_mask_texture);
        glUniform1i(glGetUniformLocation(selection_post_shader_prog, "selMaskTex"), 1);
        glBindVertexArray(quad_vao);
        glDrawArrays(GL_TRIANGLES, 0, 6);
        glBindVertexArray(0);
        glEnable(GL_DEPTH_TEST);
        glDepthMask(GL_TRUE);
        render_wireframe();
#ifdef _WIN32
        SwapBuffers(hdc);
#endif
    }
    void Renderer::Impl::clear_frame()
    {
        if (!initialized)
            return;
#ifdef _WIN32
        wglMakeCurrent(hdc, hglrc);
#endif
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, width, height);
        glDisable(GL_SCISSOR_TEST);
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glDepthMask(GL_TRUE);
        glClearColor(bg_r, bg_g, bg_b, bg_a);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        glFlush();
#ifdef _WIN32
        SwapBuffers(hdc);
#endif
        pick_buffer.clear();
    }
    void Renderer::Impl::suspend()
    {
        suspended = true;
        clear_frame();
    }
    void Renderer::Impl::resume()
    {
        suspended = false;
        first_frame = true;
        accumulator = 0.0f;
    }
    void Renderer::Impl::resize(int w, int h)
    {
        if (w <= 0 || h <= 0)
            return;
        width = w;
        height = h;
        camera->aspect_ratio = static_cast<float>(w) / static_cast<float>(h);
#ifdef _WIN32
        ContextGuard guard(hdc, hglrc);
#endif
        glViewport(0, 0, w, h);
        resize_oit(w, h);
        resize_pick(w, h);
        if (suspended)
            clear_frame();
    }
    void Renderer::render() { pImpl->render(); }
    void Renderer::resize(int width_px, int height_px) { pImpl->resize(width_px, height_px); }
    void Renderer::shutdown() { pImpl->shutdown(); }
    void Renderer::suspend() { pImpl->suspend(); }
    void Renderer::resume() { pImpl->resume(); }
    void Renderer::clear_frame() { pImpl->clear_frame(); }
    int Renderer::pick(int screen_x_px, int screen_y_px)
    {
        return pImpl->pick_at(screen_x_px, screen_y_px);
    }
    void Renderer::set_background_color(float r, float g, float b, float a)
    {
        pImpl->bg_r = r;
        pImpl->bg_g = g;
        pImpl->bg_b = b;
        pImpl->bg_a = a;
    }
    void Renderer::set_plan_texture(
        const std::string &pixels_rgba,
        int width_px,
        int height_px,
        float page_width,
        float page_height,
        float plane_x,
        float plane_y,
        float plane_z,
        float opacity,
        bool visible,
        bool flip_u,
        bool flip_v)
    {
        pImpl->set_plan_texture(
            pixels_rgba,
            width_px,
            height_px,
            page_width,
            page_height,
            plane_x,
            plane_y,
            plane_z,
            opacity,
            visible,
            flip_u,
            flip_v);
    }
    void Renderer::clear_plan_texture() { pImpl->clear_plan_texture(); }
    void Renderer::set_plan_texture_visibility(bool visible)
    {
        pImpl->set_plan_texture_visibility(visible);
    }
    void Renderer::set_plan_texture_opacity(float opacity)
    {
        pImpl->set_plan_texture_opacity(opacity);
    }
    void Renderer::set_edges_visible(bool visible) { pImpl->show_edges = visible; }
    void Renderer::set_section_cut(int axis, bool enabled, float position)
    {
        pImpl->set_section_cut(axis, enabled, position);
    }
    bool Renderer::section_cut_enabled(int axis) const
    {
        return axis >= 0 && axis <= 1 && pImpl->cut_enabled[axis];
    }
    float Renderer::section_cut_position(int axis) const
    {
        return (axis >= 0 && axis <= 1) ? pImpl->cut_position[axis] : 0.0f;
    }
    bool Renderer::edges_visible() const { return pImpl->show_edges; }
    void Renderer::set_instanced_model(const std::string &glb_bytes, float units_per_metre)
    {
        pImpl->set_instanced_model(glb_bytes, units_per_metre);
    }
    void Renderer::clear_instanced_model()
    {
        if (!pImpl->initialized)
            return;
#ifdef _WIN32
        ContextGuard guard(pImpl->hdc, pImpl->hglrc);
#endif
        pImpl->clear_instanced_model();
    }
    bool Renderer::has_instanced_model() const { return !pImpl->model_parts.empty(); }
    std::vector<std::string> Renderer::instanced_model_components() const
    {
        std::vector<std::string> names;
        for (const auto &component : pImpl->model_components)
            names.push_back(component.name);
        return names;
    }
    void Renderer::set_model_instances_visible(bool visible) { pImpl->show_instances = visible; }
    bool Renderer::model_instances_visible() const { return pImpl->show_instances; }
    Box3 Renderer::render_bounds() const
    {
        Box3 bounds = scene.get_bounds();
        Box3 extra = pImpl->instance_bounds();
        if (!extra.is_empty())
        {
            bounds.expand(extra.min);
            bounds.expand(extra.max);
        }
        return bounds;
    }
    int Renderer::get_samples() const { return pImpl->samples; }
}
