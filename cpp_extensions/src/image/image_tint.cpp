#include "image_tint.hpp"
#include <algorithm>
namespace ost_image
{
    TintedImage tint_grayscale(
        const uint8_t *grayscale_data,
        int width,
        int height,
        uint8_t r,
        uint8_t g,
        uint8_t b,
        uint8_t paper_threshold)
    {
        TintedImage result;
        result.width = width;
        result.height = height;
        const size_t pixel_count = static_cast<size_t>(width) * height;
        result.pixels.resize(pixel_count * 4);
        uint8_t *dst = result.pixels.data();
        const int threshold = std::max(1, static_cast<int>(paper_threshold));
        for (size_t i = 0; i < pixel_count; ++i)
        {
            uint8_t gray = grayscale_data[i];
            size_t dst_idx = i * 4;
            if (gray < paper_threshold)
            {
                int coverage = threshold - static_cast<int>(gray);
                uint8_t alpha = static_cast<uint8_t>(
                    std::clamp((coverage * 255 + threshold / 2) / threshold, 1, 255));
                dst[dst_idx + 0] = b;
                dst[dst_idx + 1] = g;
                dst[dst_idx + 2] = r;
                dst[dst_idx + 3] = alpha;
            }
            else
            {
                dst[dst_idx + 0] = 0;
                dst[dst_idx + 1] = 0;
                dst[dst_idx + 2] = 0;
                dst[dst_idx + 3] = 0;
            }
        }
        return result;
    }
}
