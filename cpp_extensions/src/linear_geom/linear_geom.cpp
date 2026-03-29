#include "linear_geom.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
namespace ost_linear
{
    static inline bool has_slope_factor(std::optional<double> rise,
                                        std::optional<double> run,
                                        double &rise_v, double &run_v)
    {
        if (!rise.has_value() || !run.has_value() || *run == 0.0)
            return false;
        rise_v = *rise;
        run_v = *run;
        return true;
    }
    static double perp_slope(double dx, double dy)
    {
        if (dx == 0.0)
            return std::numeric_limits<double>::infinity();
        if (dy == 0.0)
            return 0.0;
        return -dx / dy;
    }
    static std::vector<Vec2> curve_pts_impl(
        double x1, double y1, double x2, double y2,
        double cx, double cy, int segs)
    {
        double m1x = (x1 + cx) * 0.5, m1y = (y1 + cy) * 0.5;
        double m2x = (cx + x2) * 0.5, m2y = (cy + y2) * 0.5;
        double ps1 = perp_slope(cx - x1, cy - y1);
        double ps2 = perp_slope(x2 - cx, y2 - cy);
        constexpr double INF = std::numeric_limits<double>::infinity();
        double ctr_x = INF, ctr_y = INF;
        bool found = false;
        if (ps1 == INF && ps2 != INF)
        {
            ctr_x = m1x;
            ctr_y = m2y + ps2 * (m1x - m2x);
            found = true;
        }
        else if (ps2 == INF && ps1 != INF)
        {
            ctr_x = m2x;
            ctr_y = m1y + ps1 * (m2x - m1x);
            found = true;
        }
        else if (std::abs(ps1 - ps2) > 1e-10)
        {
            ctr_x = (m2y - m1y + ps1 * m1x - ps2 * m2x) / (ps1 - ps2);
            ctr_y = m1y + ps1 * (ctr_x - m1x);
            found = true;
        }
        if (found)
        {
            double r1 = std::hypot(ctr_x - x1, ctr_y - y1);
            double r2 = std::hypot(ctr_x - x2, ctr_y - y2);
            double rc = std::hypot(ctr_x - cx, ctr_y - cy);
            if (std::abs(r1 - r2) < 0.1 && std::abs(r1 - rc) < 0.1)
            {
                double r = r1;
                double a_s = std::atan2(y1 - ctr_y, x1 - ctr_x);
                double a_e = std::atan2(y2 - ctr_y, x2 - ctr_x);
                double cross1 = (x1 - ctr_x) * (cy - ctr_y) -
                                (y1 - ctr_y) * (cx - ctr_x);
                double cross2 = (cx - ctr_x) * (y2 - ctr_y) -
                                (cy - ctr_y) * (x2 - ctr_x);
                bool clockwise = (cross1 + cross2) < 0;
                if (clockwise)
                {
                    if (a_e > a_s)
                        a_e -= 2.0 * M_PI;
                }
                else
                {
                    if (a_e < a_s)
                        a_e += 2.0 * M_PI;
                }
                double a_diff = a_e - a_s;
                std::vector<Vec2> pts;
                pts.reserve(static_cast<size_t>(segs) + 1);
                for (int i = 0; i <= segs; ++i)
                {
                    double t = static_cast<double>(i) / segs;
                    double a = a_s + t * a_diff;
                    pts.push_back({ctr_x + r * std::cos(a),
                                   ctr_y + r * std::sin(a)});
                }
                return pts;
            }
        }
        std::vector<Vec2> pts;
        pts.reserve(static_cast<size_t>(segs) + 1);
        for (int i = 0; i <= segs; ++i)
        {
            double t = static_cast<double>(i) / segs;
            double u = 1.0 - t;
            pts.push_back({u * u * x1 + 2.0 * u * t * cx + t * t * x2,
                           u * u * y1 + 2.0 * u * t * cy + t * t * y2});
        }
        return pts;
    }
    double calc_chord_length(double x1, double y1, double x2, double y2)
    {
        return std::hypot(x2 - x1, y2 - y1);
    }
    int calc_adaptive_segs(double x1, double y1, double x2, double y2,
                           double cx, double cy)
    {
        double chord_d = std::hypot(x2 - x1, y2 - y1);
        double curve_d = (std::hypot(cx - x1, cy - y1) +
                          std::hypot(x2 - cx, y2 - cy)) *
                         0.8;
        int base_s = std::clamp(
            static_cast<int>(std::max(chord_d, curve_d) / 5.0), 6, 64);
        if (chord_d > 0)
        {
            double dx = x2 - x1, dy = y2 - y1;
            double t = std::clamp(
                ((cx - x1) * dx + (cy - y1) * dy) / (dx * dx + dy * dy),
                0.0, 1.0);
            double offset = std::hypot(cx - (x1 + t * dx), cy - (y1 + t * dy));
            base_s += static_cast<int>(offset / 5.0);
        }
        return std::clamp(base_s, 6, 64);
    }
    std::vector<Vec2> gen_curve_pts(double x1, double y1, double x2, double y2,
                                    double cx, double cy, int segs)
    {
        return curve_pts_impl(x1, y1, x2, y2, cx, cy, segs);
    }
    std::vector<Vec2> gen_adv_curve_pts(double x1, double y1, double x2, double y2,
                                        double cx, double cy, int segments)
    {
        double m1x = (x1 + cx) * 0.5, m1y = (y1 + cy) * 0.5;
        double m2x = (cx + x2) * 0.5, m2y = (cy + y2) * 0.5;
        double ps1 = perp_slope(cx - x1, cy - y1);
        double ps2 = perp_slope(x2 - cx, y2 - cy);
        constexpr double INF = std::numeric_limits<double>::infinity();
        double ctr_x = INF, ctr_y = INF;
        bool found = false;
        if (ps1 == INF)
        {
            if (ps2 != INF)
            {
                ctr_x = m1x;
                ctr_y = m2y + ps2 * (m1x - m2x);
                found = true;
            }
        }
        else if (ps2 == INF)
        {
            ctr_x = m2x;
            ctr_y = m1y + ps1 * (m2x - m1x);
            found = true;
        }
        else if (std::abs(ps1 - ps2) > 1e-10)
        {
            ctr_x = (m2y - m1y + ps1 * m1x - ps2 * m2x) / (ps1 - ps2);
            ctr_y = m1y + ps1 * (ctr_x - m1x);
            found = true;
        }
        if (found)
        {
            double r1 = std::hypot(ctr_x - x1, ctr_y - y1);
            double r2 = std::hypot(ctr_x - x2, ctr_y - y2);
            double rc = std::hypot(ctr_x - cx, ctr_y - cy);
            if (std::abs(r1 - r2) < 0.1 && std::abs(r1 - rc) < 0.1)
            {
                double r = r1;
                double a_s = std::atan2(y1 - ctr_y, x1 - ctr_x);
                double a_e = std::atan2(y2 - ctr_y, x2 - ctr_x);
                double cross1 = (x1 - ctr_x) * (cy - ctr_y) -
                                (y1 - ctr_y) * (cx - ctr_x);
                double cross2 = (cx - ctr_x) * (y2 - ctr_y) -
                                (cy - ctr_y) * (x2 - ctr_x);
                bool clockwise = (cross1 + cross2) < 0;
                if (clockwise)
                {
                    if (a_e > a_s)
                        a_e -= 2.0 * M_PI;
                }
                else
                {
                    if (a_e < a_s)
                        a_e += 2.0 * M_PI;
                }
                double a_diff = a_e - a_s;
                std::vector<Vec2> pts;
                pts.reserve(static_cast<size_t>(segments) + 1);
                for (int i = 0; i <= segments; ++i)
                {
                    double t = static_cast<double>(i) / segments;
                    pts.push_back({ctr_x + r * std::cos(a_s + t * a_diff),
                                   ctr_y + r * std::sin(a_s + t * a_diff)});
                }
                return pts;
            }
        }
        return curve_pts_impl(x1, y1, x2, y2, cx, cy, segments);
    }
    std::pair<std::vector<Vec3>, bool> calc_linear_mesh_verts(
        double x1, double y1, double x2, double y2,
        double height, double thickness, double z_offset,
        std::optional<double> rise, std::optional<double> run)
    {
        double dx = x2 - x1, dy = y2 - y1;
        double h_len = std::hypot(dx, dy);
        if (h_len < 0.001)
            return {{}, false};
        double dx_n = dx / h_len, dy_n = dy / h_len;
        double px = -dy_n * thickness * 0.5;
        double py = dx_n * thickness * 0.5;
        double rise_v = 0, run_v = 0;
        bool has_slope = has_slope_factor(rise, run, rise_v, run_v);
        std::vector<Vec3> verts(8);
        if (has_slope && rise_v != 0.0 && run_v != 0.0)
        {
            double v_chg = h_len * std::abs(rise_v) / std::abs(run_v);
            bool up = (rise_v > 0 && run_v > 0) || (rise_v < 0 && run_v < 0);
            double z_b = z_offset;
            if (up)
            {
                verts[0] = {x1 + px, y1 + py, z_b};
                verts[1] = {x1 - px, y1 - py, z_b};
                verts[2] = {x2 - px, y2 - py, z_b + v_chg};
                verts[3] = {x2 + px, y2 + py, z_b + v_chg};
                verts[4] = {x1 + px, y1 + py, z_offset + height};
                verts[5] = {x1 - px, y1 - py, z_offset + height};
                verts[6] = {x2 - px, y2 - py, z_offset + height + v_chg};
                verts[7] = {x2 + px, y2 + py, z_offset + height + v_chg};
            }
            else
            {
                verts[0] = {x1 + px, y1 + py, z_b + v_chg};
                verts[1] = {x1 - px, y1 - py, z_b + v_chg};
                verts[2] = {x2 - px, y2 - py, z_b};
                verts[3] = {x2 + px, y2 + py, z_b};
                verts[4] = {x1 + px, y1 + py, z_offset + height + v_chg};
                verts[5] = {x1 - px, y1 - py, z_offset + height + v_chg};
                verts[6] = {x2 - px, y2 - py, z_offset + height};
                verts[7] = {x2 + px, y2 + py, z_offset + height};
            }
        }
        else
        {
            double z_b = z_offset;
            verts[0] = {x1 + px, y1 + py, z_b};
            verts[1] = {x1 - px, y1 - py, z_b};
            verts[2] = {x2 - px, y2 - py, z_b};
            verts[3] = {x2 + px, y2 + py, z_b};
            verts[4] = {x1 + px, y1 + py, z_offset + height};
            verts[5] = {x1 - px, y1 - py, z_offset + height};
            verts[6] = {x2 - px, y2 - py, z_offset + height};
            verts[7] = {x2 + px, y2 + py, z_offset + height};
        }
        return {verts, has_slope};
    }
    std::vector<Face> get_curved_mesh_faces(int n)
    {
        std::vector<Face> faces;
        faces.reserve(static_cast<size_t>((n - 1) * 8 + 4));
        auto u = [](int v) -> uint32_t
        { return static_cast<uint32_t>(v); };
        for (int i = 0; i < n - 1; ++i)
        {
            faces.push_back({u(i), u(i + 1 + n), u(i + 1)});
            faces.push_back({u(i), u(i + n), u(i + 1 + n)});
        }
        for (int i = 0; i < n - 1; ++i)
        {
            faces.push_back({u(2 * n + i), u(2 * n + i + 1 + n), u(2 * n + i + n)});
            faces.push_back({u(2 * n + i), u(2 * n + i + 1), u(2 * n + i + 1 + n)});
        }
        for (int i = 0; i < n - 1; ++i)
        {
            faces.push_back({u(i), u(2 * n + i + 1), u(2 * n + i)});
            faces.push_back({u(i), u(i + 1), u(2 * n + i + 1)});
        }
        for (int i = 0; i < n - 1; ++i)
        {
            faces.push_back({u(n + i), u(3 * n + i + 1), u(n + i + 1)});
            faces.push_back({u(n + i), u(3 * n + i), u(3 * n + i + 1)});
        }
        faces.push_back({u(0), u(3 * n), u(n)});
        faces.push_back({u(0), u(2 * n), u(3 * n)});
        faces.push_back({u(n - 1), u(n + n - 1), u(3 * n + n - 1)});
        faces.push_back({u(n - 1), u(3 * n + n - 1), u(2 * n + n - 1)});
        return faces;
    }
    std::vector<Edge> get_curved_mesh_edges(int n)
    {
        std::vector<Edge> edges;
        edges.reserve(static_cast<size_t>((n - 1) * 4 + n * 2));
        auto u = [](int v) -> uint32_t
        { return static_cast<uint32_t>(v); };
        for (int i = 0; i < n - 1; ++i)
        {
            edges.push_back({u(i), u(i + 1)});
            edges.push_back({u(n + i), u(n + i + 1)});
            edges.push_back({u(2 * n + i), u(2 * n + i + 1)});
            edges.push_back({u(3 * n + i), u(3 * n + i + 1)});
        }
        for (int i = 0; i < n; ++i)
        {
            edges.push_back({u(i), u(2 * n + i)});
            edges.push_back({u(n + i), u(3 * n + i)});
        }
        return edges;
    }
    std::array<double, 6> proc_curved_pos(
        const std::vector<double> &position,
        double x1, double y1, double x2, double y2,
        double cx, double cy)
    {
        if (position.size() >= 7)
        {
            x1 = position[0];
            y1 = position[1];
            x2 = position[2];
            y2 = position[3];
            double offset = -position[6];
            double mx = (x1 + x2) * 0.5, my = (y1 + y2) * 0.5;
            double dx = x2 - x1, dy = y2 - y1;
            double length = std::hypot(dx, dy);
            if (length > 0)
            {
                dx /= length;
                dy /= length;
                cx = mx - dy * offset;
                cy = my + dx * offset;
            }
        }
        return {x1, y1, x2, y2, cx, cy};
    }
    int calc_curve_segs(double x1, double y1, double x2, double y2,
                        double cx, double cy,
                        std::optional<int> segments)
    {
        if (!segments.has_value())
            return calc_adaptive_segs(x1, y1, x2, y2, cx, cy);
        return *segments;
    }
    std::tuple<bool, double, bool> proc_slope_params(
        std::optional<double> rise, std::optional<double> run, double h_len)
    {
        double rise_v = 0, run_v = 0;
        if (!has_slope_factor(rise, run, rise_v, run_v))
            return {false, 0.0, false};
        if (rise_v == 0.0 || run_v == 0.0)
            return {false, 0.0, false};
        double v_chg = h_len * std::abs(rise_v) / std::abs(run_v);
        bool up = (rise_v > 0 && run_v > 0) || (rise_v < 0 && run_v < 0);
        return {true, v_chg, up};
    }
    std::tuple<std::vector<Vec3>, std::vector<Vec3>,
               std::vector<Vec3>, std::vector<Vec3>>
    gen_curved_wall_pts(const std::vector<Vec2> &curve_pts,
                        double thickness, double height, double z_offset,
                        bool has_slope, double v_chg, bool slope_up)
    {
        size_t n = curve_pts.size();
        std::vector<Vec3> inner_bot, outer_bot, inner_top, outer_top;
        inner_bot.reserve(n);
        outer_bot.reserve(n);
        inner_top.reserve(n);
        outer_top.reserve(n);
        double half_t = thickness * 0.5;
        for (size_t i = 0; i < n; ++i)
        {
            double cx = curve_pts[i][0], cy = curve_pts[i][1];
            double dx, dy;
            if (i == 0 && n > 1)
            {
                dx = curve_pts[1][0] - cx;
                dy = curve_pts[1][1] - cy;
            }
            else if (i == n - 1)
            {
                dx = cx - curve_pts[i - 1][0];
                dy = cy - curve_pts[i - 1][1];
            }
            else
            {
                double px_v = curve_pts[i - 1][0], py_v = curve_pts[i - 1][1];
                double nx_v = curve_pts[i + 1][0], ny_v = curve_pts[i + 1][1];
                dx = ((cx - px_v) + (nx_v - cx)) * 0.5;
                dy = ((cy - py_v) + (ny_v - cy)) * 0.5;
            }
            double length = std::hypot(dx, dy);
            if (length > 0)
            {
                dx /= length;
                dy /= length;
            }
            double nx = -dy, ny = dx;
            double ix = cx + nx * half_t, iy = cy + ny * half_t;
            double ox = cx - nx * half_t, oy = cy - ny * half_t;
            double z_off = 0.0;
            if (has_slope && n > 1)
            {
                double t = static_cast<double>(i) / static_cast<double>(n - 1);
                z_off = slope_up ? t * v_chg : (1.0 - t) * v_chg;
            }
            double z_b = z_offset + z_off;
            double z_t = z_offset + height + z_off;
            inner_bot.push_back({ix, iy, z_b});
            outer_bot.push_back({ox, oy, z_b});
            inner_top.push_back({ix, iy, z_t});
            outer_top.push_back({ox, oy, z_t});
        }
        return {std::move(inner_bot), std::move(outer_bot),
                std::move(inner_top), std::move(outer_top)};
    }
    std::pair<std::vector<Vec2>, std::vector<Vec2>>
    gen_thick_curve_offsets(const std::vector<Vec2> &curve_pts, double thickness)
    {
        size_t n = curve_pts.size();
        std::vector<Vec2> inner, outer;
        inner.reserve(n);
        outer.reserve(n);
        double half_t = thickness * 0.5;
        for (size_t i = 0; i < n; ++i)
        {
            double cx = curve_pts[i][0], cy = curve_pts[i][1];
            double dx, dy;
            if (i == 0 && n > 1)
            {
                dx = curve_pts[1][0] - cx;
                dy = curve_pts[1][1] - cy;
            }
            else if (i == n - 1)
            {
                dx = cx - curve_pts[i - 1][0];
                dy = cy - curve_pts[i - 1][1];
            }
            else
            {
                dx = (curve_pts[i + 1][0] - curve_pts[i - 1][0]) * 0.5;
                dy = (curve_pts[i + 1][1] - curve_pts[i - 1][1]) * 0.5;
            }
            double length = std::hypot(dx, dy);
            if (length > 0)
            {
                dx /= length;
                dy /= length;
            }
            double nx = -dy, ny = dx;
            inner.push_back({cx + nx * half_t, cy + ny * half_t});
            outer.push_back({cx - nx * half_t, cy - ny * half_t});
        }
        return {std::move(inner), std::move(outer)};
    }
}
