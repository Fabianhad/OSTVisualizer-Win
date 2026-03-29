#pragma once
#include <cstdint>
#include <vector>
namespace ost_image
{
    struct TintedImage
    {
        int width;
        int height;
        std::vector<uint8_t> pixels;
    };
    TintedImage tint_grayscale(
        const uint8_t *grayscale_data,
        int width,
        int height,
        uint8_t r,
        uint8_t g,
        uint8_t b,
        uint8_t paper_threshold = 235);
}
