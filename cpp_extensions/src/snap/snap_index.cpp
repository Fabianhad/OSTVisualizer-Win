#include "snap/snap_index.hpp"
#include <cmath>
#include <limits>
namespace ost_snap
{
    namespace
    {
        constexpr float kDegenerateEpsilonSq = 1.0e-12f;
        float dist_sq(float ax, float ay, float bx, float by)
        {
            const float dx = ax - bx;
            const float dy = ay - by;
            return dx * dx + dy * dy;
        }
        bool finite_segment(float x1, float y1, float x2, float y2)
        {
            return std::isfinite(x1) && std::isfinite(y1) &&
                   std::isfinite(x2) && std::isfinite(y2);
        }
    }
    void SnapIndex::build(const std::vector<RawSegment> &raw)
    {
        segments_.clear();
        segments_.reserve(raw.size());
        for (const auto &entry : raw)
        {
            const auto [x1, y1, x2, y2] = entry;
            if (!finite_segment(x1, y1, x2, y2))
            {
                continue;
            }
            const float len_sq = dist_sq(x1, y1, x2, y2);
            if (!std::isfinite(len_sq) || len_sq <= kDegenerateEpsilonSq)
            {
                continue;
            }
            segments_.push_back(Segment{x1, y1, x2, y2});
        }
    }
    std::optional<SnapHit> SnapIndex::query(float x, float y, float radius) const
    {
        if (radius < 0.0f || segments_.empty())
        {
            return std::nullopt;
        }
        const float radius_sq = radius * radius;
        float best_endpoint_dist_sq = std::numeric_limits<float>::infinity();
        float best_midpoint_dist_sq = std::numeric_limits<float>::infinity();
        float best_perpendicular_dist_sq = std::numeric_limits<float>::infinity();
        SnapHit best_endpoint{0.0f, 0.0f, NONE, -1};
        SnapHit best_midpoint{0.0f, 0.0f, NONE, -1};
        SnapHit best_perpendicular{0.0f, 0.0f, NONE, -1};
        auto consider = [&](float hx,
                            float hy,
                            SnapKind kind,
                            int32_t segment_index,
                            float &best_dist_sq,
                            SnapHit &best_hit)
        {
            const float d_sq = dist_sq(x, y, hx, hy);
            if (d_sq <= radius_sq && d_sq < best_dist_sq)
            {
                best_dist_sq = d_sq;
                best_hit = SnapHit{hx, hy, static_cast<int32_t>(kind), segment_index};
            }
        };
        for (std::size_t i = 0; i < segments_.size(); ++i)
        {
            const Segment &s = segments_[i];
            const int32_t segment_index = static_cast<int32_t>(i);
            consider(
                s.x1,
                s.y1,
                ENDPOINT,
                segment_index,
                best_endpoint_dist_sq,
                best_endpoint);
            consider(
                s.x2,
                s.y2,
                ENDPOINT,
                segment_index,
                best_endpoint_dist_sq,
                best_endpoint);
            const float dx = s.x2 - s.x1;
            const float dy = s.y2 - s.y1;
            const float len_sq = dx * dx + dy * dy;
            if (len_sq <= 0.0f)
            {
                continue;
            }
            consider(
                s.x1 + 0.5f * dx,
                s.y1 + 0.5f * dy,
                MIDPOINT,
                segment_index,
                best_midpoint_dist_sq,
                best_midpoint);
            const float t = ((x - s.x1) * dx + (y - s.y1) * dy) / len_sq;
            if (t > 0.0f && t < 1.0f)
            {
                consider(
                    s.x1 + t * dx,
                    s.y1 + t * dy,
                    PERPENDICULAR,
                    segment_index,
                    best_perpendicular_dist_sq,
                    best_perpendicular);
            }
        }
        if (std::isfinite(best_endpoint_dist_sq))
        {
            return best_endpoint;
        }
        if (std::isfinite(best_midpoint_dist_sq))
        {
            return best_midpoint;
        }
        if (std::isfinite(best_perpendicular_dist_sq))
        {
            return best_perpendicular;
        }
        return std::nullopt;
    }
    std::size_t SnapIndex::size() const noexcept
    {
        return segments_.size();
    }
}
