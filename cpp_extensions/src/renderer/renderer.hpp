#pragma once
#include <vector>
#include <memory>
#include <string>
#include <set>
#include <cstdint>
#include <limits>
#include <glm/glm.hpp>
namespace ost_renderer
{
    class Scene;
    class Camera;
    struct Vec3
    {
        float x = 0, y = 0, z = 0;
        Vec3() = default;
        Vec3(float x, float y, float z) : x(x), y(y), z(z) {}
        glm::vec3 to_glm() const { return glm::vec3(x, y, z); }
        static Vec3 from_glm(const glm::vec3 &v) { return Vec3(v.x, v.y, v.z); }
    };
    struct Color
    {
        float r = 1, g = 1, b = 1, a = 1;
        Color() = default;
        Color(float r, float g, float b, float a) : r(r), g(g), b(b), a(a) {}
    };
    struct Box3
    {
        static constexpr float kMaxFloat = std::numeric_limits<float>::max();
        Vec3 min{kMaxFloat, kMaxFloat, kMaxFloat};
        Vec3 max{-kMaxFloat, -kMaxFloat, -kMaxFloat};
        bool is_empty() const { return min.x > max.x; }
        void expand(const Vec3 &point);
        void clear();
    };
    class MeshData
    {
    public:
        std::vector<Vec3> vertices;
        std::vector<Vec3> normals;
        std::vector<uint32_t> indices;
        Color color;
        std::string condition_uid;
        std::string takeoff_uid;
        void set_vertices(const std::vector<float> &flat_verts);
        void set_normals(const std::vector<float> &flat_norms);
    };
    class Camera
    {
    public:
        float fov = 45.0f;
        float near_plane = 0.1f;
        float far_plane = 10000.0f;
        float aspect_ratio = 1.0f;
        Vec3 position{0, -2000, 1000};
        Vec3 target{0, 0, 0};
        Vec3 prev_position{0, -2000, 1000};
        Vec3 prev_target{0, 0, 0};
        float interpolation_alpha = 0.0f;
        glm::vec2 rotational_velocity{0.0f};
        glm::vec3 pan_velocity{0.0f};
        Camera();
        void rotate(float delta_x, float delta_y);
        void pan(float delta_x, float delta_y);
        void zoom(float delta);
        void update(float delta_time);
        void interpolate(float alpha);
        bool has_velocity() const;
        void show_object(const Box3 &bounds);
        void restore_state(const Vec3 &saved_position,
                           const Vec3 &saved_target,
                           float saved_fov,
                           const Box3 &bounds);
        void reset();
        void get_view_matrix(float *out_matrix) const;
        void get_projection_matrix(float *out_matrix) const;

    private:
        float configure_clip_planes(const Box3 &bounds);
    };
    class Scene
    {
    public:
        void clear();
        void add_mesh(const MeshData &mesh);
        Box3 get_bounds() const;
        bool empty() const { return meshes_.empty(); }
        // Attach the owning renderer's GL context so scene mutations
        // (clear / add_mesh) can make that context current before making
        // GL calls. Safe to leave unattached for default-constructed
        // scenes — guards become no-ops and the current context is used.
        void attach_gl_context(void *hdc, void *hglrc);
        struct GLMesh
        {
            uint32_t vao = 0, vbo = 0, ebo = 0;
            uint32_t line_vao = 0, line_ibo = 0;
            size_t index_count = 0;
            size_t line_count = 0;
            bool transparent = false;
            int mesh_index = -1;
            Color color;
            std::string condition_uid;
            std::string takeoff_uid;
        };
        const std::vector<GLMesh> &get_meshes() const { return meshes_; }
        size_t mesh_count() const { return meshes_.size(); }
        const std::string &get_condition_uid(int index) const;
        const std::string &get_takeoff_uid(int index) const;
        void set_selected(int mesh_index, bool selected);
        void clear_selection();
        const std::set<int> &get_selected() const { return selected_; }
        bool is_selected(int index) const { return selected_.count(index) > 0; }

    private:
        std::vector<GLMesh> meshes_;
        Box3 bounds_;
        std::set<int> selected_;
        static const std::string kEmptyString;
        void *gl_hdc_ = nullptr;
        void *gl_hglrc_ = nullptr;
    };
    class Renderer
    {
    public:
        explicit Renderer(uintptr_t native_window_handle);
        ~Renderer();
        Renderer(const Renderer &) = delete;
        Renderer &operator=(const Renderer &) = delete;
        void render();
        // Native viewport, render-target, and pick coordinates are physical pixels.
        void resize(int width_px, int height_px);
        void shutdown();
        void suspend();
        void resume();
        void clear_frame();
        int pick(int screen_x_px, int screen_y_px);
        void set_background_color(float r, float g, float b, float a);
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
        int get_samples() const;
        Scene scene;
        Camera camera;

    private:
        class Impl;
        std::unique_ptr<Impl> pImpl;
    };
}
