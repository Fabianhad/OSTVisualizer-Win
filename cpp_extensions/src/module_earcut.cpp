#include <nanobind/nanobind.h>
#include <nanobind/stl/array.h>
#include <array>
#include <nanobind/stl/vector.h>
#include <stdexcept>
#include <vector>

#include "earcut/earcut.hpp"
namespace nb = nanobind;
std::vector<uint32_t> earcut_triangulate(
    const std::vector<double> &flat_coords,
    const std::vector<uint32_t> &hole_indices,
    uint32_t dim)
{
    if (flat_coords.empty())
    {
        return {};
    }
    if (dim < 2)
    {
        throw std::invalid_argument("dim must be at least 2");
    }
    if (flat_coords.size() % dim != 0)
    {
        throw std::invalid_argument("coordinate data length must be divisible by dim");
    }
    size_t vertex_count = flat_coords.size() / dim;
    if (vertex_count < 3)
    {
        return {};
    }
    using Point = std::array<double, 2>;
    std::vector<std::vector<Point>> polygon;
    std::vector<size_t> ring_starts;
    ring_starts.push_back(0);
    size_t previous_start = 0;
    for (uint32_t h : hole_indices)
    {
        size_t start = static_cast<size_t>(h);
        if (start <= previous_start || start >= vertex_count)
        {
            throw std::invalid_argument(
                "hole indices must be strictly increasing and within the vertex range");
        }
        if (start - previous_start < 3)
        {
            throw std::invalid_argument("each polygon ring must contain at least 3 vertices");
        }
        ring_starts.push_back(start);
        previous_start = start;
    }
    if (vertex_count - previous_start < 3)
    {
        throw std::invalid_argument("each polygon ring must contain at least 3 vertices");
    }
    ring_starts.push_back(vertex_count);
    for (size_t r = 0; r + 1 < ring_starts.size(); ++r)
    {
        size_t start = ring_starts[r];
        size_t end = ring_starts[r + 1];
        std::vector<Point> ring;
        ring.reserve(end - start);
        for (size_t i = start; i < end; ++i)
        {
            double x = flat_coords[i * dim];
            double y = flat_coords[i * dim + 1];
            ring.push_back({x, y});
        }
        if (!ring.empty())
        {
            polygon.push_back(std::move(ring));
        }
    }
    if (polygon.empty() || polygon[0].size() < 3)
    {
        return {};
    }
    mapbox::detail::Earcut<uint32_t> ec;
    ec(polygon);
    return ec.indices;
}
NB_MODULE(ost_earcut, m)
{
    m.doc() = "Native earcut triangulation module";
    m.def("earcut", &earcut_triangulate,
          nb::arg("data"),
          nb::arg("hole_indices") = std::vector<uint32_t>(),
          nb::arg("dim") = 2,
          "Triangulate a polygon with optional holes.\n\n"
          "Args:\n"
          "    data: Flat array of vertex coordinates [x1,y1,x2,y2,...]\n"
          "    hole_indices: Start indices for each hole in vertex count\n"
          "    dim: Coordinate dimension (2 for 2D)\n\n"
          "Returns:\n"
          "    List of triangle indices");
}
