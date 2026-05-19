#pragma once
#include <cstddef>
#include <cstdint>
#include <optional>
#include <tuple>
#include <vector>
namespace ost_snap
{
    struct Segment
    {
        float x1;
        float y1;
        float x2;
        float y2;
    };
    enum SnapKind : int32_t
    {
        NONE = -1,
        GRID = 0,
        ENDPOINT = 1,
        MIDPOINT = 2,
        PERPENDICULAR = 3,
    };
    using RawSegment = std::tuple<float, float, float, float>;
    using SnapHit = std::tuple<float, float, int32_t, int32_t>;
    class SnapIndex
    {
    public:
        void build(const std::vector<RawSegment> &raw);
        std::optional<SnapHit> query(float x, float y, float radius) const;
        std::size_t size() const noexcept;

    private:
        std::vector<Segment> segments_;
    };
}
