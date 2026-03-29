#include "coord_transform.hpp"
namespace ost_coord
{
    constexpr double PDF_POINTS_PER_INCH = 72.0;
    std::vector<double> transform_vertices_to_2d(
        const std::vector<double> &position,
        double scale_ratio, double view_scale)
    {
        size_t len = position.size();
        if (len < 2)
            return position;
        size_t count = (len / 2) * 2;
        double factor = PDF_POINTS_PER_INCH * view_scale / scale_ratio;
        std::vector<double> result;
        result.reserve(count);
        for (size_t i = 0; i < count; i += 2)
        {
            result.push_back(position[i] * factor);
            result.push_back(position[i + 1] * factor);
        }
        return result;
    }
    std::vector<Vec2> transform_vertices_to_3d(
        const std::vector<Vec2> &vertices,
        double scale_ratio)
    {
        double inv = 1.0 / scale_ratio;
        std::vector<Vec2> result;
        result.reserve(vertices.size());
        for (const auto &v : vertices)
        {
            result.push_back({-(v[0] * inv), v[1] * inv});
        }
        return result;
    }
    std::vector<std::vector<Vec2>> transform_holes_to_3d(
        const std::vector<std::vector<Vec2>> &holes,
        double scale_ratio)
    {
        std::vector<std::vector<Vec2>> result;
        result.reserve(holes.size());
        for (const auto &hole : holes)
        {
            result.push_back(transform_vertices_to_3d(hole, scale_ratio));
        }
        return result;
    }
    Vec2 reverse_rotation(
        double x_units, double y_units,
        int rotation_delta,
        double pdf_width_pts, double pdf_height_pts,
        double points_per_unit)
    {
        rotation_delta = ((rotation_delta % 360) + 360) % 360;
        double pdf_x, pdf_y;
        switch (rotation_delta)
        {
        case 90:
            pdf_y = x_units * points_per_unit;
            pdf_x = pdf_width_pts - (y_units * points_per_unit);
            break;
        case 180:
            pdf_x = pdf_width_pts - (x_units * points_per_unit);
            pdf_y = pdf_height_pts - (y_units * points_per_unit);
            break;
        case 270:
            pdf_y = pdf_height_pts - (x_units * points_per_unit);
            pdf_x = y_units * points_per_unit;
            break;
        default:
            pdf_x = x_units * points_per_unit;
            pdf_y = pdf_height_pts - (y_units * points_per_unit);
            break;
        }
        return {pdf_x, pdf_y};
    }
    std::vector<Vec2> ost_to_pdf_coordinates(
        const std::vector<double> &ost_position,
        double pdf_width_pts, double pdf_height_pts,
        double scale_factor1, double scale_factor2,
        int rotation,
        bool flip_x, bool flip_y,
        double coord_scale_x, double coord_scale_y,
        bool is_page_rotated, bool auto_rotate_180,
        double coord_offset_x, double coord_offset_y)
    {
        size_t len = ost_position.size();
        if (len < 2)
            return {};
        double units_per_inch = scale_factor2 / scale_factor1;
        double units_per_point = units_per_inch / PDF_POINTS_PER_INCH;
        double points_per_unit = 1.0 / units_per_point;
        int ost_rotation = ((rotation % 360) + 360) % 360;
        double final_width_units, final_height_units;
        if (ost_rotation == 90 || ost_rotation == 270)
        {
            final_width_units = pdf_height_pts * units_per_point;
            final_height_units = pdf_width_pts * units_per_point;
        }
        else
        {
            final_width_units = pdf_width_pts * units_per_point;
            final_height_units = pdf_height_pts * units_per_point;
        }
        double actual_width = pdf_width_pts * coord_scale_x;
        double actual_height = pdf_height_pts * coord_scale_y;
        std::vector<Vec2> vertices;
        vertices.reserve(len / 2);
        for (size_t i = 0; i + 1 < len; i += 2)
        {
            double x_units = ost_position[i];
            double y_units = ost_position[i + 1];
            if (flip_x)
                x_units = final_width_units - x_units;
            if (flip_y)
                y_units = final_height_units - y_units;
            auto [pdf_x, pdf_y] = reverse_rotation(
                x_units, y_units,
                ost_rotation,
                pdf_width_pts, pdf_height_pts,
                points_per_unit);
            pdf_x *= coord_scale_x;
            pdf_y *= coord_scale_y;
            if (is_page_rotated)
            {
                double orig_x = pdf_x;
                pdf_x = pdf_y;
                pdf_y = actual_width - orig_x;
            }
            if (auto_rotate_180)
            {
                pdf_x = actual_width - pdf_x;
                pdf_y = actual_height - pdf_y;
            }
            pdf_x += coord_offset_x;
            pdf_y += coord_offset_y;
            vertices.push_back({pdf_x, pdf_y});
        }
        return vertices;
    }
}
