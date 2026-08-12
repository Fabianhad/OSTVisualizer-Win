#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>

namespace ost_page_transform
{
    inline void validate_dimensions(double width, double height)
    {
        if (!std::isfinite(width) || !std::isfinite(height) ||
            width <= 0.0 || height <= 0.0)
            throw std::invalid_argument("Page dimensions must be finite and positive");
    }

    inline int normalize_quarter_turn(int rotation)
    {
        int normalized = ((rotation % 360) + 360) % 360;
        if (normalized % 90 != 0)
            throw std::invalid_argument("Page rotation must be a multiple of 90 degrees");
        return normalized;
    }

    inline std::array<double, 2> output_dimensions(
        double width, double height, int rotation)
    {
        validate_dimensions(width, height);
        int normalized = normalize_quarter_turn(rotation);
        if (normalized == 90 || normalized == 270)
            return {height, width};
        return {width, height};
    }

    inline std::array<double, 2> transform_top_left_point(
        double width,
        double height,
        int rotation,
        bool flip_x,
        bool flip_y,
        double x,
        double y)
    {
        if (!std::isfinite(x) || !std::isfinite(y))
            throw std::invalid_argument("Page coordinates must be finite");
        validate_dimensions(width, height);
        int normalized = normalize_quarter_turn(rotation);

        double transformed_x = flip_x ? width - x : x;
        double transformed_y = flip_y ? height - y : y;
        switch (normalized)
        {
        case 90:
            return {transformed_y, width - transformed_x};
        case 180:
            return {width - transformed_x, height - transformed_y};
        case 270:
            return {height - transformed_y, transformed_x};
        default:
            return {transformed_x, transformed_y};
        }
    }

    inline bool dimensions_match(
        double actual_width,
        double actual_height,
        double expected_width,
        double expected_height)
    {
        auto matches = [](double actual, double expected)
        {
            double tolerance = 1.0e-9 * std::max({1.0, std::abs(actual), std::abs(expected)});
            return std::abs(actual - expected) <= tolerance;
        };
        return matches(actual_width, expected_width) &&
               matches(actual_height, expected_height);
    }
}
