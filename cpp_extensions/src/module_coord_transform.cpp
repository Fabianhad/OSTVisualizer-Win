#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/array.h>
#include "coord_transform/coord_transform.hpp"
namespace nb = nanobind;
NB_MODULE(ost_coord_transform, m)
{
      m.doc() = "Native coordinate transformation utilities";
      m.def("transform_to_2d", &ost_coord::transform_to_2d,
            nb::arg("ost_x"), nb::arg("ost_y"),
            nb::arg("scale_ratio"), nb::arg("view_scale"),
            "Transform OST coordinates to 2D screen pixels.");
      m.def("transform_to_3d", &ost_coord::transform_to_3d,
            nb::arg("ost_x"), nb::arg("ost_y"),
            nb::arg("scale_ratio"),
            "Transform OST coordinates to 3D real units.");
      m.def("transform_vertices_to_2d", &ost_coord::transform_vertices_to_2d,
            nb::arg("position"),
            nb::arg("scale_ratio"), nb::arg("view_scale"),
            "Batch transform flat position list [x0,y0,x1,y1,...] to screen pixels.");
      m.def("transform_vertices_to_3d", &ost_coord::transform_vertices_to_3d,
            nb::arg("vertices"),
            nb::arg("scale_ratio"),
            "Batch transform vertex tuples to 3D real units.");
      m.def("transform_holes_to_3d", &ost_coord::transform_holes_to_3d,
            nb::arg("holes"),
            nb::arg("scale_ratio"),
            "Batch transform hole vertex lists to 3D real units.");
      m.def("ost_to_pdf_coordinates", &ost_coord::ost_to_pdf_coordinates,
            nb::arg("ost_position"),
            nb::arg("pdf_width_pts"), nb::arg("pdf_height_pts"),
            nb::arg("scale_factor1"), nb::arg("scale_factor2"),
            nb::arg("rotation"),
            nb::arg("flip_x"), nb::arg("flip_y"),
            "Convert OST positions to canonical exported-page coordinates with rotation and flips.");
      m.attr("__version__") = "1.0.0";
}
