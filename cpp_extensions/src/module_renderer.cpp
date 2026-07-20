#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/string.h>
#include <stdexcept>
#include "renderer/renderer.hpp"
namespace nb = nanobind;
using namespace nb::literals;
using namespace ost_renderer;
NB_MODULE(ost_renderer, m)
{
    m.doc() = "OST 3D Renderer - OpenGL backend with PyGFX-like API";
    nb::class_<Vec3>(m, "Vec3")
        .def(nb::init<float, float, float>())
        .def_rw("x", &Vec3::x)
        .def_rw("y", &Vec3::y)
        .def_rw("z", &Vec3::z);
    nb::class_<Color>(m, "Color")
        .def(nb::init<float, float, float, float>())
        .def_rw("r", &Color::r)
        .def_rw("g", &Color::g)
        .def_rw("b", &Color::b)
        .def_rw("a", &Color::a);
    nb::class_<Box3>(m, "Box3")
        .def(nb::init<>())
        .def_rw("min", &Box3::min)
        .def_rw("max", &Box3::max)
        .def("is_empty", &Box3::is_empty);
    nb::class_<MeshData>(m, "MeshData")
        .def(nb::init<>())
        .def("set_vertices", &MeshData::set_vertices, "flat_array")
        .def("set_normals", &MeshData::set_normals, "flat_array")
        .def_rw("indices", &MeshData::indices)
        .def_rw("color", &MeshData::color)
        .def_rw("condition_uid", &MeshData::condition_uid)
        .def_rw("takeoff_uid", &MeshData::takeoff_uid);
    nb::class_<Camera>(m, "Camera")
        .def(nb::init<>())
        .def("rotate", &Camera::rotate, "delta_x", "delta_y")
        .def("pan", &Camera::pan, "delta_x", "delta_y")
        .def("zoom", &Camera::zoom, "delta")
        .def("show_object", &Camera::show_object, "bounds")
        .def("reset", &Camera::reset)
        .def("has_velocity", &Camera::has_velocity)
        .def_rw("fov", &Camera::fov)
        .def_rw("position", &Camera::position)
        .def_rw("target", &Camera::target);
    nb::class_<Scene>(m, "Scene")
        .def(nb::init<>())
        .def("clear", &Scene::clear)
        .def("add_mesh", &Scene::add_mesh, "mesh_data")
        .def("get_bounds", &Scene::get_bounds)
        .def("empty", &Scene::empty)
        .def("mesh_count", &Scene::mesh_count)
        .def("get_condition_uid", &Scene::get_condition_uid, "index")
        .def("get_takeoff_uid", &Scene::get_takeoff_uid, "index")
        .def("set_selected", &Scene::set_selected, "mesh_index", "selected")
        .def("clear_selection", &Scene::clear_selection)
        .def("is_selected", &Scene::is_selected, "index");
    nb::class_<Renderer>(m, "Renderer")
        .def(nb::init<uintptr_t>(), "native_window_handle")
        .def("render", &Renderer::render)
        .def("resize", &Renderer::resize, "width_px", "height_px")
        .def("shutdown", &Renderer::shutdown)
        .def("suspend", &Renderer::suspend)
        .def("resume", &Renderer::resume)
        .def("clear_frame", &Renderer::clear_frame)
        .def("set_background_color", &Renderer::set_background_color, "r", "g", "b", "a")
        .def(
            "set_plan_texture",
            [](Renderer &renderer,
               nb::bytes pixels_rgba,
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
                char *buffer = nullptr;
                Py_ssize_t length = 0;
                if (PyBytes_AsStringAndSize(pixels_rgba.ptr(), &buffer, &length) != 0)
                    throw std::invalid_argument("pixels_rgba must be bytes");
                renderer.set_plan_texture(
                    std::string(buffer, static_cast<size_t>(length)),
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
            },
            "pixels_rgba"_a,
            "width_px"_a,
            "height_px"_a,
            "page_width"_a,
            "page_height"_a,
            "plane_x"_a,
            "plane_y"_a,
            "plane_z"_a,
            "opacity"_a,
            "visible"_a,
            "flip_u"_a,
            "flip_v"_a)
        .def("clear_plan_texture", &Renderer::clear_plan_texture)
        .def("set_plan_texture_visibility", &Renderer::set_plan_texture_visibility, "visible")
        .def("set_plan_texture_opacity", &Renderer::set_plan_texture_opacity, "opacity")
        .def("pick", &Renderer::pick, "screen_x_px", "screen_y_px")
        .def_rw("scene", &Renderer::scene)
        .def_rw("camera", &Renderer::camera);
}
