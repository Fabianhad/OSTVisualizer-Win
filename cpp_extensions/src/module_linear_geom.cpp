#include <nanobind/nanobind.h>
#include <nanobind/stl/array.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/vector.h>
#include "linear_geom/linear_geom.hpp"
namespace nb = nanobind;
NB_MODULE(ost_linear_geom, m)
{
      m.doc() = "Native linear geometry utilities for curve generation and mesh building";
      m.def("calc_chord_length", &ost_linear::calc_chord_length,
            nb::arg("x1"), nb::arg("y1"), nb::arg("x2"), nb::arg("y2"),
            "Euclidean distance between two 2D points.");
      m.def("calc_adaptive_segs", &ost_linear::calc_adaptive_segs,
            nb::arg("x1"), nb::arg("y1"), nb::arg("x2"), nb::arg("y2"),
            nb::arg("cx"), nb::arg("cy"),
            "Calculate adaptive segment count for a curve.");
      m.def("gen_curve_pts", &ost_linear::gen_curve_pts,
            nb::arg("x1"), nb::arg("y1"), nb::arg("x2"), nb::arg("y2"),
            nb::arg("cx"), nb::arg("cy"), nb::arg("segs") = 24,
            "Generate arc or quadratic Bezier curve points.");
      m.def("gen_adv_curve_pts", &ost_linear::gen_adv_curve_pts,
            nb::arg("x1"), nb::arg("y1"), nb::arg("x2"), nb::arg("y2"),
            nb::arg("cx"), nb::arg("cy"), nb::arg("segments"),
            "Generate curve points with arc preference and Bezier fallback.");
      m.def("calc_linear_mesh_verts", &ost_linear::calc_linear_mesh_verts,
            nb::arg("x1"), nb::arg("y1"), nb::arg("x2"), nb::arg("y2"),
            nb::arg("height"), nb::arg("thickness"),
            nb::arg("z_offset") = 0.0,
            nb::arg("rise") = nb::none(), nb::arg("run") = nb::none(),
            "Calculate 8 vertices for a linear segment mesh box.");
      m.def("get_curved_mesh_faces", &ost_linear::get_curved_mesh_faces,
            nb::arg("n"),
            "Generate face indices for a curved wall mesh with n curve points.");
      m.def("get_curved_mesh_edges", &ost_linear::get_curved_mesh_edges,
            nb::arg("n"),
            "Generate edge indices for a curved wall mesh with n curve points.");
      m.def("proc_curved_pos", &ost_linear::proc_curved_pos,
            nb::arg("position"), nb::arg("x1"), nb::arg("y1"),
            nb::arg("x2"), nb::arg("y2"), nb::arg("cx"), nb::arg("cy"),
            "Process curved position from position list or pass-through coords.");
      m.def("calc_curve_segs", &ost_linear::calc_curve_segs,
            nb::arg("x1"), nb::arg("y1"), nb::arg("x2"), nb::arg("y2"),
            nb::arg("cx"), nb::arg("cy"), nb::arg("segments") = nb::none(),
            "Calculate curve segments (adaptive if segments is None).");
      m.def("proc_slope_params", &ost_linear::proc_slope_params,
            nb::arg("rise") = nb::none(), nb::arg("run") = nb::none(),
            nb::arg("h_len") = 0.0,
            "Process slope parameters and return (has_slope, v_chg, slope_up).");
      m.def("gen_curved_wall_pts", &ost_linear::gen_curved_wall_pts,
            nb::arg("curve_pts"), nb::arg("thickness"), nb::arg("height"),
            nb::arg("z_offset"),
            nb::arg("has_slope") = false, nb::arg("v_chg") = 0.0,
            nb::arg("slope_up") = false,
            "Generate 4 vertex strips (inner/outer bottom/top) for a curved wall.");
      m.def("gen_thick_curve_offsets", &ost_linear::gen_thick_curve_offsets,
            nb::arg("curve_pts"), nb::arg("thickness"),
            "Compute inner/outer normal-offset polygons for a thick curved path.");
      m.attr("__version__") = "1.0.0";
}
