#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/array.h>
#include "geom_utils/geom_utils.hpp"
namespace nb = nanobind;
NB_MODULE(ost_geom_utils, m)
{
      m.doc() = "Native geometry utilities for hit testing and polygon validation";
      m.def("point_to_segment_distance", &ost_geom::point_to_segment_distance,
            nb::arg("px"), nb::arg("py"),
            nb::arg("x1"), nb::arg("y1"),
            nb::arg("x2"), nb::arg("y2"),
            "Distance from point (px, py) to line segment (x1, y1)-(x2, y2).");
      m.def("segments_intersect", &ost_geom::segments_intersect,
            nb::arg("p1"), nb::arg("p2"),
            nb::arg("p3"), nb::arg("p4"),
            "Test if segment p1-p2 intersects segment p3-p4 (strict crossing).");
      m.def("polygon_is_valid", &ost_geom::polygon_is_valid,
            nb::arg("pts"),
            "Check polygon has no self-intersecting edges.");
      m.def("polyline_self_intersects", &ost_geom::polyline_self_intersects,
            nb::arg("pts"),
            "Check if an open polyline has any self-intersections.");
      m.def("signed_area", &ost_geom::signed_area,
            nb::arg("pos"),
            "Signed area of polygon from flat coordinate list [x0,y0,x1,y1,...].");
      m.attr("__version__") = "1.0.0";
}
