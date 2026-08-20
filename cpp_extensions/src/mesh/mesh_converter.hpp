#pragma once
#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/array.h>
#include "mesh_data.hpp"
namespace nb = nanobind;
namespace ost_geometry
{
    CppMeshData from_python_meshdata(nb::object py_mesh);
    nb::dict to_python_meshdata_args(const CppMeshData &mesh);
    std::vector<std::array<double, 3>> extract_vertices(nb::object py_vertices);
    std::vector<std::array<uint32_t, 3>> extract_faces(nb::object py_faces);
    std::vector<std::array<uint32_t, 2>> extract_edges(nb::object py_edges);
    nb::list vertices_to_python(const std::vector<std::array<double, 3>> &vertices);
    nb::list faces_to_python(const std::vector<std::array<uint32_t, 3>> &faces);
    nb::list edges_to_python(const std::vector<std::array<uint32_t, 2>> &edges);
}
