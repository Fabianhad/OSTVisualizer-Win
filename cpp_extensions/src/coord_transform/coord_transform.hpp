#pragma once
#include "../common/vec_types.hpp"
#include <vector>
namespace ost_coord
{
    inline Vec2 transform_to_2d(
        double ost_x, double ost_y,
        double scale_ratio, double view_scale)
    {
        constexpr double PDF_POINTS_PER_INCH = 72.0;
        double factor = PDF_POINTS_PER_INCH * view_scale / scale_ratio;
        return {ost_x * factor, ost_y * factor};
    }
    inline Vec2 transform_to_3d(
        double ost_x, double ost_y,
        double scale_ratio)
    {
        return {-(ost_x / scale_ratio), ost_y / scale_ratio};
    }
    std::vector<double> transform_vertices_to_2d(
        const std::vector<double> &position,
        double scale_ratio, double view_scale);
    std::vector<Vec2> transform_vertices_to_3d(
        const std::vector<Vec2> &vertices,
        double scale_ratio);
    std::vector<std::vector<Vec2>> transform_holes_to_3d(
        const std::vector<std::vector<Vec2>> &holes,
        double scale_ratio);
    Vec2 reverse_rotation(
        double x_units, double y_units,
        int rotation_delta,
        double pdf_width_pts, double pdf_height_pts,
        double points_per_unit);
    std::vector<Vec2> ost_to_pdf_coordinates(
        const std::vector<double> &ost_position,
        double pdf_width_pts, double pdf_height_pts,
        double scale_factor1, double scale_factor2,
        int rotation,
        bool flip_x, bool flip_y,
        double coord_offset_x, double coord_offset_y);
}
