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
#ifdef _WIN32
#include <windows.h>
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
        unpack_vec3(vertices, flat_verts);
    }
    void MeshData::set_normals(const std::vector<float> &flat_norms)
    {
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
    void Camera::show_object(const Box3 &bounds)
    {
        if (bounds.is_empty())
        {
            reset();
            return;
        }
        Vec3 center(
            (bounds.min.x + bounds.max.x) * 0.5f,
            (bounds.min.y + bounds.max.y) * 0.5f,
            (bounds.min.z + bounds.max.z) * 0.5f);
        float size = std::max({bounds.max.x - bounds.min.x,
                               bounds.max.y - bounds.min.y,
                               bounds.max.z - bounds.min.z});
        if (size < 1.0f)
            size = 100.0f;
        near_plane = std::max(0.1f, size * 0.001f);
        far_plane = std::max(10000.0f, size * 20.0f);
        target = center;
        position.x = center.x;
        position.y = center.y - size * 1.5f;
        position.z = center.z + size * 0.5f;
        prev_position = position;
        prev_target = target;
    }
    void Camera::reset()
    {
        position = Vec3(0, -2000, 1000);
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
        bounds_.clear();
        selected_.clear();
    }
    void Scene::add_mesh(const MeshData &data)
    {
        if (data.vertices.empty() || data.indices.empty())
            return;
        ContextGuard guard(gl_hdc_, gl_hglrc_);
        GLMesh mesh;
        mesh.index_count = data.indices.size();
        mesh.transparent = data.color.a < 0.99f;
        mesh.mesh_index = (int)meshes_.size();
        mesh.color = data.color;
        mesh.condition_uid = data.condition_uid;
        mesh.takeoff_uid = data.takeoff_uid;
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
            struct UEdge
            {
                uint32_t a, b;
                bool operator==(const UEdge &o) const { return a == o.a && b == o.b; }
            };
            struct UEdgeHash
            {
                size_t operator()(const UEdge &e) const
                {
                    return std::hash<uint64_t>{}(((uint64_t)e.a << 32) | e.b);
                }
            };
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
                auto &a = data.vertices[data.indices[t * 3]];
                auto &b = data.vertices[data.indices[t * 3 + 1]];
                auto &c = data.vertices[data.indices[t * 3 + 2]];
                glm::vec3 e1(b.x - a.x, b.y - a.y, b.z - a.z);
                glm::vec3 e2(c.x - a.x, c.y - a.y, c.z - a.z);
                return glm::normalize(glm::cross(e1, e2));
            };
            for (int t = 0; t < triCount; t++)
            {
                uint32_t idx[3] = {data.indices[t * 3], data.indices[t * 3 + 1], data.indices[t * 3 + 2]};
                for (int e = 0; e < 3; e++)
                {
                    uint32_t va = idx[e], vb = idx[(e + 1) % 3];
                    uint64_t key = ((uint64_t)std::min(va, vb) << 32) | std::max(va, vb);
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
out vec4 vertexColor;
out vec3 normal;
out vec3 worldPos;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    vec4 worldPosition = model * vec4(aPos, 1.0);
    worldPos = worldPosition.xyz;
    normal = mat3(transpose(inverse(model))) * aNormal;
    vertexColor = aColor;
    gl_Position = projection * view * worldPosition;
}
)";
    const char *opaque_fragment_shader = R"(
#version 330 core
in vec4 vertexColor;
in vec3 normal;
in vec3 worldPos;
out vec4 FragColor;
uniform float ambientIntensity = 0.55;
uniform vec3 keyLightDir = normalize(vec3(500.0, -500.0, 500.0));
uniform float keyLightIntensity = 0.45;
uniform vec3 fillLightDir = normalize(vec3(-500.0, 500.0, 500.0));
uniform float fillLightIntensity = 0.35;
uniform vec3 rimLightDir = normalize(vec3(0.0, 500.0, -500.0));
uniform float rimLightIntensity = 0.2;
void main() {
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
out vec4 FragColor;
uniform vec4 u_meshId;
void main() {
    FragColor = u_meshId;
}
)";
    const char *flat_color_fragment_shader = R"(
#version 330 core
out vec4 FragColor;
uniform vec4 u_color;
void main() {
    FragColor = u_color;
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
        glm::mat4 view, projection;
        camera->get_view_matrix(glm::value_ptr(view));
        camera->get_projection_matrix(glm::value_ptr(projection));
        glUniformMatrix4fv(glGetUniformLocation(shader, "model"), 1, GL_FALSE, glm::value_ptr(model));
        glUniformMatrix4fv(glGetUniformLocation(shader, "view"), 1, GL_FALSE, glm::value_ptr(view));
        glUniformMatrix4fv(glGetUniformLocation(shader, "projection"), 1, GL_FALSE, glm::value_ptr(projection));
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
            clear_plan_texture();
            if (opaque_shader)
                glDeleteProgram(opaque_shader);
            if (transparent_accum_shader)
                glDeleteProgram(transparent_accum_shader);
            if (plan_texture_shader)
                glDeleteProgram(plan_texture_shader);
            if (composite_shader)
                glDeleteProgram(composite_shader);
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
        glBindVertexArray(0);
        glEnable(GL_DEPTH_TEST);
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
        glm::mat4 view, projection;
        camera->get_view_matrix(glm::value_ptr(view));
        camera->get_projection_matrix(glm::value_ptr(projection));
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
        for (auto &m : scene->get_meshes())
        {
            if (m.transparent)
                continue;
            glBindVertexArray(m.vao);
            glDrawElements(GL_TRIANGLES, static_cast<GLsizei>(m.index_count), GL_UNSIGNED_INT, 0);
        }
        glBindVertexArray(0);
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
        glBindVertexArray(0);
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
    int Renderer::get_samples() const { return pImpl->samples; }
}
