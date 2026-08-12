#include "coord_transform.hpp"
#include "../common/page_transform.hpp"
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
    std::vector<Vec2> ost_to_pdf_coordinates(
        const std::vector<double> &ost_position,
        double pdf_width_pts, double pdf_height_pts,
        double scale_factor1, double scale_factor2,
        int rotation,
        bool flip_x, bool flip_y)
    {
        size_t len = ost_position.size();
        if (len < 2)
            return {};
        if (!std::isfinite(scale_factor1) || !std::isfinite(scale_factor2) ||
            scale_factor1 <= 0.0 || scale_factor2 <= 0.0)
            throw std::invalid_argument(
                "Page scale factors must be finite and positive");
        double points_per_unit =
            PDF_POINTS_PER_INCH * scale_factor1 / scale_factor2;
        auto output_size = ost_page_transform::output_dimensions(
            pdf_width_pts, pdf_height_pts, rotation);
        std::vector<Vec2> vertices;
        vertices.reserve(len / 2);
        for (size_t i = 0; i + 1 < len; i += 2)
        {
            auto point = ost_page_transform::transform_top_left_point(
                pdf_width_pts,
                pdf_height_pts,
                rotation,
                flip_x,
                flip_y,
                ost_position[i] * points_per_unit,
                ost_position[i + 1] * points_per_unit);
            vertices.push_back({point[0], output_size[1] - point[1]});
        }
        return vertices;
    }
}
