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
        uint8_t lut_r[256];
        uint8_t lut_g[256];
        uint8_t lut_b[256];
        for (int i = 0; i < 256; ++i)
        {
            int strength = 255 - i;
            lut_r[i] = static_cast<uint8_t>((r * strength) / 255);
            lut_g[i] = static_cast<uint8_t>((g * strength) / 255);
            lut_b[i] = static_cast<uint8_t>((b * strength) / 255);
        }
        for (size_t i = 0; i < pixel_count; ++i)
        {
            uint8_t gray = grayscale_data[i];
            size_t dst_idx = i * 4;
            if (gray < paper_threshold)
            {
                dst[dst_idx + 0] = lut_b[gray];
                dst[dst_idx + 1] = lut_g[gray];
                dst[dst_idx + 2] = lut_r[gray];
                dst[dst_idx + 3] = 255;
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
