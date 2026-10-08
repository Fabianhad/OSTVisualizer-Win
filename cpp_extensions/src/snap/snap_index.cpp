#include "snap/snap_index.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
namespace ost_snap
{
    namespace
    {
        constexpr float kDegenerateEpsilonSq = 1.0e-12f;
        constexpr std::size_t kMaxGridSide = 512;
        constexpr std::size_t kMaxCellsPerSegment = 4096;
        constexpr float kMinCellSize = 1.0e-3f;
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
        std::size_t cell_of(double value, double origin, double cell, std::size_t count)
        {
            const double position = std::floor((value - origin) / cell);
            if (!(position > 0.0))
            {
                return 0;
            }
            const double last = static_cast<double>(count - 1);
            return static_cast<std::size_t>(std::min(position, last));
        }
    }
    void SnapIndex::build(const std::vector<RawSegment> &raw)
    {
        segments_.clear();
        cells_.clear();
        columns_ = 0;
        rows_ = 0;
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
        if (segments_.empty())
        {
            return;
        }
        float min_x = std::numeric_limits<float>::infinity();
        float min_y = std::numeric_limits<float>::infinity();
        float max_x = -std::numeric_limits<float>::infinity();
        float max_y = -std::numeric_limits<float>::infinity();
        for (const Segment &s : segments_)
        {
            min_x = std::min({min_x, s.x1, s.x2});
            min_y = std::min({min_y, s.y1, s.y2});
            max_x = std::max({max_x, s.x1, s.x2});
            max_y = std::max({max_y, s.y1, s.y2});
        }
        const std::size_t side = std::clamp<std::size_t>(
            static_cast<std::size_t>(std::ceil(std::sqrt(static_cast<double>(segments_.size())))),
            1,
            kMaxGridSide);
        const double extent = std::max(static_cast<double>(max_x) - min_x, static_cast<double>(max_y) - min_y);
        cell_size_ = std::max(static_cast<float>(extent / static_cast<double>(side)), kMinCellSize);
        origin_x_ = min_x;
        origin_y_ = min_y;
        columns_ = std::clamp<std::size_t>(static_cast<std::size_t>(std::ceil((static_cast<double>(max_x) - min_x) / cell_size_)), 1, kMaxGridSide);
        rows_ = std::clamp<std::size_t>(static_cast<std::size_t>(std::ceil((static_cast<double>(max_y) - min_y) / cell_size_)), 1, kMaxGridSide);
        cells_.assign(columns_ * rows_ + 1, {});
        std::vector<int32_t> &wide = cells_.back();
        for (std::size_t i = 0; i < segments_.size(); ++i)
        {
            const Segment &s = segments_[i];
            const std::size_t c0 = cell_of(std::min(s.x1, s.x2), origin_x_, cell_size_, columns_);
            const std::size_t c1 = cell_of(std::max(s.x1, s.x2), origin_x_, cell_size_, columns_);
            const std::size_t r0 = cell_of(std::min(s.y1, s.y2), origin_y_, cell_size_, rows_);
            const std::size_t r1 = cell_of(std::max(s.y1, s.y2), origin_y_, cell_size_, rows_);
            const int32_t index = static_cast<int32_t>(i);
            if ((c1 - c0 + 1) * (r1 - r0 + 1) > kMaxCellsPerSegment)
            {
                wide.push_back(index);
                continue;
            }
            for (std::size_t r = r0; r <= r1; ++r)
            {
                for (std::size_t c = c0; c <= c1; ++c)
                {
                    cells_[r * columns_ + c].push_back(index);
                }
            }
        }
    }
    std::vector<int32_t> SnapIndex::candidates(float x, float y, float radius) const
    {
        std::vector<int32_t> found;
        if (!(radius >= 0.0f) || segments_.empty() || !std::isfinite(x) || !std::isfinite(y))
        {
            return found;
        }
        const double left = static_cast<double>(x) - radius;
        const double right = static_cast<double>(x) + radius;
        const double top = static_cast<double>(y) - radius;
        const double bottom = static_cast<double>(y) + radius;
        found = cells_.back();
        const std::size_t c0 = cell_of(left, origin_x_, cell_size_, columns_);
        const std::size_t c1 = cell_of(right, origin_x_, cell_size_, columns_);
        const std::size_t r0 = cell_of(top, origin_y_, cell_size_, rows_);
        const std::size_t r1 = cell_of(bottom, origin_y_, cell_size_, rows_);
        for (std::size_t r = r0; r <= r1; ++r)
        {
            for (std::size_t c = c0; c <= c1; ++c)
            {
                const std::vector<int32_t> &cell = cells_[r * columns_ + c];
                found.insert(found.end(), cell.begin(), cell.end());
            }
        }
        std::sort(found.begin(), found.end());
        found.erase(std::unique(found.begin(), found.end()), found.end());
        return found;
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
        for (const int32_t segment_index : candidates(x, y, radius))
        {
            const Segment &s = segments_[static_cast<std::size_t>(segment_index)];
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
    std::size_t SnapIndex::grid_columns() const noexcept
    {
        return columns_;
    }
    std::size_t SnapIndex::grid_rows() const noexcept
    {
        return rows_;
    }
}
