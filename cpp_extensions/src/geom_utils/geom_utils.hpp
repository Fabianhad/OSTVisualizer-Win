#pragma once
#include "../common/vec_types.hpp"
#include <vector>
namespace ost_geom
{
    double point_to_segment_distance(
        double px, double py,
        double x1, double y1,
        double x2, double y2);
    bool segments_intersect(
        const Vec2 &p1, const Vec2 &p2,
        const Vec2 &p3, const Vec2 &p4);
    bool polygon_is_valid(const std::vector<Vec2> &pts);
    bool polyline_self_intersects(const std::vector<Vec2> &pts);
    double signed_area(const std::vector<double> &pos);
}
