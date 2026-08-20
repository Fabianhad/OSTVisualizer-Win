#pragma once
#include "../common/vec_types.hpp"
#include <optional>
#include <tuple>
#include <vector>
namespace ost_linear
{
    double calc_chord_length(double x1, double y1, double x2, double y2);
    int calc_adaptive_segs(double x1, double y1, double x2, double y2,
                           double cx, double cy);
    std::vector<Vec2> gen_curve_pts(double x1, double y1, double x2, double y2,
                                    double cx, double cy, int segs = 24);
    std::vector<Vec2> gen_adv_curve_pts(double x1, double y1, double x2, double y2,
                                        double cx, double cy, int segments);
    std::pair<std::vector<Vec3>, bool> calc_linear_mesh_verts(
        double x1, double y1, double x2, double y2,
        double height, double thickness, double z_offset,
        std::optional<double> rise, std::optional<double> run);
    std::vector<Face> get_curved_mesh_faces(int n);
    std::vector<Edge> get_curved_mesh_edges(int n);
    std::array<double, 6> proc_curved_pos(
        const std::vector<double> &position,
        double x1, double y1, double x2, double y2,
        double cx, double cy);
    int calc_curve_segs(double x1, double y1, double x2, double y2,
                        double cx, double cy,
                        std::optional<int> segments = std::nullopt);
    std::tuple<bool, double, bool> proc_slope_params(
        std::optional<double> rise, std::optional<double> run, double h_len);
    std::tuple<std::vector<Vec3>, std::vector<Vec3>,
               std::vector<Vec3>, std::vector<Vec3>>
    gen_curved_wall_pts(const std::vector<Vec2> &curve_pts,
                        double thickness, double height, double z_offset,
                        bool has_slope = false, double v_chg = 0.0,
                        bool slope_up = false);
    std::pair<std::vector<Vec2>, std::vector<Vec2>>
    gen_thick_curve_offsets(const std::vector<Vec2> &curve_pts, double thickness);
}
