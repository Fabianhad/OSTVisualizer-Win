#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/array.h>
#include <nanobind/stl/string.h>
#include "dxf_writer.hpp"
#include "mesh_data.hpp"
namespace nb = nanobind;
using namespace ost_geometry;
NB_MODULE(ost_dxf, m)
{
    m.doc() = "Native DXF Exporter module";
    nb::class_<CppMeshData>(m, "CppMeshData")
        .def(nb::init<>())
        .def_rw("vertices", &CppMeshData::vertices)
        .def_rw("faces", &CppMeshData::faces)
        .def_rw("edges", &CppMeshData::edges);
    nb::class_<RGBColor>(m, "RGBColor")
        .def(nb::init<>())
        .def(nb::init<uint8_t, uint8_t, uint8_t>(), nb::arg("r"), nb::arg("g"), nb::arg("b"))
        .def_rw("r", &RGBColor::r)
        .def_rw("g", &RGBColor::g)
        .def_rw("b", &RGBColor::b)
        .def("to_aci", &RGBColor::to_aci)
        .def_static("from_hex", &RGBColor::from_hex, nb::arg("hex"));
    nb::class_<DXFLine>(m, "DXFLine")
        .def(nb::init<>())
        .def(nb::init<const std::array<double, 3> &, const std::array<double, 3> &, const std::string &>())
        .def_rw("start", &DXFLine::start)
        .def_rw("end", &DXFLine::end)
        .def_rw("layer", &DXFLine::layer);
    nb::class_<LayeredMesh>(m, "LayeredMesh")
        .def(nb::init<>())
        .def(nb::init<const CppMeshData &, const std::string &>())
        .def_rw("mesh", &LayeredMesh::mesh)
        .def_rw("layer_name", &LayeredMesh::layer_name);
    nb::class_<DXFWriter>(m, "DXFWriter")
        .def(nb::init<>())
        .def("add_layer", static_cast<void (DXFWriter::*)(const std::string &, const RGBColor &)>(&DXFWriter::add_layer))
        .def("add_layer", static_cast<void (DXFWriter::*)(const std::string &, const std::string &)>(&DXFWriter::add_layer))
        .def("add_line", &DXFWriter::add_line, nb::arg("start"), nb::arg("end"), nb::arg("layer") = "0")
        .def("add_mesh_as_lines", &DXFWriter::add_mesh_as_lines, nb::arg("mesh"), nb::arg("layer") = "0")
        .def("add_meshes_as_lines", &DXFWriter::add_meshes_as_lines)
        .def("save", &DXFWriter::save)
        .def("clear", &DXFWriter::clear)
        .def("get_line_count", &DXFWriter::get_line_count)
        .def("get_layer_count", &DXFWriter::get_layer_count);
    m.def("hex_to_rgb", [](const std::string &hex)
          { return RGBColor::from_hex(hex); }, nb::arg("hex"));
}