#include "geom_utils.hpp"
#include <cmath>
namespace ost_geom
{
    static double cross_2d(const Vec2 &o, const Vec2 &a, const Vec2 &b)
    {
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    }
    double point_to_segment_distance(
        double px, double py,
        double x1, double y1,
        double x2, double y2)
    {
        double dx = x2 - x1;
        double dy = y2 - y1;
        double len_sq = dx * dx + dy * dy;
        if (len_sq == 0.0)
        {
            double ex = px - x1;
            double ey = py - y1;
            return std::sqrt(ex * ex + ey * ey);
        }
        double t = ((px - x1) * dx + (py - y1) * dy) / len_sq;
        if (t < 0.0)
            t = 0.0;
        else if (t > 1.0)
            t = 1.0;
        double nx = x1 + t * dx - px;
        double ny = y1 + t * dy - py;
        return std::sqrt(nx * nx + ny * ny);
    }
    bool segments_intersect(
        const Vec2 &p1, const Vec2 &p2,
        const Vec2 &p3, const Vec2 &p4)
    {
        double d1 = cross_2d(p3, p4, p1);
        double d2 = cross_2d(p3, p4, p2);
        double d3 = cross_2d(p1, p2, p3);
        double d4 = cross_2d(p1, p2, p4);
        return ((d1 > 0.0 && d2 < 0.0) || (d1 < 0.0 && d2 > 0.0)) &&
               ((d3 > 0.0 && d4 < 0.0) || (d3 < 0.0 && d4 > 0.0));
    }
    bool polygon_is_valid(const std::vector<Vec2> &pts)
    {
        size_t n = pts.size();
        if (n < 3)
            return false;
        for (size_t i = 0; i < n; ++i)
        {
            const Vec2 &p1 = pts[i];
            const Vec2 &p2 = pts[(i + 1) % n];
            for (size_t j = i + 2; j < n; ++j)
            {
                if (i == 0 && j == n - 1)
                    continue;
                const Vec2 &p3 = pts[j];
                const Vec2 &p4 = pts[(j + 1) % n];
                if (segments_intersect(p1, p2, p3, p4))
                    return false;
            }
        }
        return true;
    }
    bool polyline_self_intersects(const std::vector<Vec2> &pts)
    {
        size_t n = pts.size();
        if (n < 4)
            return false;
        for (size_t i = 0; i + 1 < n; ++i)
        {
            for (size_t j = i + 2; j + 1 < n; ++j)
            {
                if (segments_intersect(pts[i], pts[i + 1], pts[j], pts[j + 1]))
                    return true;
            }
        }
        return false;
    }
    double signed_area(const std::vector<double> &pos)
    {
        size_t n = pos.size() / 2;
        if (n < 2)
            return 0.0;
        double area = 0.0;
        for (size_t i = 0; i < n; ++i)
        {
            size_t j = (i + 1) % n;
            area += pos[i * 2] * pos[j * 2 + 1];
            area -= pos[j * 2] * pos[i * 2 + 1];
        }
        return area;
    }
}
