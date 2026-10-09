#include <nanobind/nanobind.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/vector.h>
#include "snap/snap_index.hpp"
namespace nb = nanobind;
NB_MODULE(ost_snap, m)
{
    m.doc() = "Native snap-to-line index for 2D plan placement";
    m.attr("NONE") = static_cast<int32_t>(ost_snap::NONE);
    m.attr("GRID") = static_cast<int32_t>(ost_snap::GRID);
    m.attr("ENDPOINT") = static_cast<int32_t>(ost_snap::ENDPOINT);
    m.attr("MIDPOINT") = static_cast<int32_t>(ost_snap::MIDPOINT);
    m.attr("PERPENDICULAR") = static_cast<int32_t>(ost_snap::PERPENDICULAR);
    m.attr("INTERSECTION") = static_cast<int32_t>(ost_snap::INTERSECTION);
    nb::class_<ost_snap::SnapIndex>(m, "SnapIndex")
        .def(nb::init<>())
        .def(
            "build",
            &ost_snap::SnapIndex::build,
            nb::arg("raw"),
            nb::call_guard<nb::gil_scoped_release>())
        .def(
            "query",
            &ost_snap::SnapIndex::query,
            nb::arg("x"),
            nb::arg("y"),
            nb::arg("radius"),
            nb::arg("intersections") = false)
        .def(
            "candidates",
            &ost_snap::SnapIndex::candidates,
            nb::arg("x"),
            nb::arg("y"),
            nb::arg("radius"))
        .def("size", &ost_snap::SnapIndex::size)
        .def("grid_columns", &ost_snap::SnapIndex::grid_columns)
        .def("grid_rows", &ost_snap::SnapIndex::grid_rows)
        .def("last_candidate_count", &ost_snap::SnapIndex::last_candidate_count)
        .def("last_intersection_pairs", &ost_snap::SnapIndex::last_intersection_pairs);
}
