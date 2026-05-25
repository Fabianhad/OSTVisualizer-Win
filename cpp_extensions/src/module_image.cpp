#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>
#include "image/image_tint.hpp"
namespace nb = nanobind;
using namespace ost_image;
NB_MODULE(ost_image, m)
{
    m.doc() = "High-performance image processing for OST Visualizer";
    nb::class_<TintedImage>(m, "TintedImage",
                            "A tinted image as BGRA pixel data")
        .def_ro("width", &TintedImage::width, "Width in pixels")
        .def_ro("height", &TintedImage::height, "Height in pixels")
        .def("to_bytes", [](const TintedImage &img)
             { return nb::bytes(
                   reinterpret_cast<const char *>(img.pixels.data()),
                   img.pixels.size()); }, "Get pixel data as bytes (BGRA format)");
    auto process_grayscale = [](nb::bytes grayscale_buffer, int width, int height, uint8_t r, uint8_t g, uint8_t b, uint8_t paper_threshold)
    {
        size_t expected_size = static_cast<size_t>(width) * height;
        if (grayscale_buffer.size() < expected_size)
        {
            throw std::runtime_error("Buffer too small for given dimensions");
        }
        const uint8_t *data = reinterpret_cast<const uint8_t *>(grayscale_buffer.data());
        return tint_grayscale(data, width, height, r, g, b, paper_threshold);
    };
    m.def("tint_grayscale", process_grayscale,
          nb::arg("grayscale_data"), nb::arg("width"), nb::arg("height"),
          nb::arg("r"), nb::arg("g"), nb::arg("b"),
          nb::arg("paper_threshold") = 235,
          R"doc(
Tint a grayscale image with a color while preserving antialias coverage.
Args:
    grayscale_data: bytes containing grayscale pixel data (1 byte per pixel)
    width: Image width in pixels
    height: Image height in pixels
    r: Red component of tint color (0-255)
    g: Green component of tint color (0-255)
    b: Blue component of tint color (0-255)
    paper_threshold: Grayscale value at or above which pixels are transparent (default: 235)
Returns:
    TintedImage with BGRA pixel data. Dark pixels are opaque and gray edge pixels
    become partially transparent tinted pixels.
Example:
    import ost_image
    result = ost_image.tint_grayscale(gray_bytes, w, h, 255, 80, 80)
    qimage = QImage(result.to_bytes(), w, h, QImage.Format.Format_ARGB32)
)doc");
    m.def("tint_red", [process_grayscale](nb::bytes grayscale_buffer, int width, int height)
          { return process_grayscale(grayscale_buffer, width, height, 255, 80, 80, 235); }, nb::arg("grayscale_data"), nb::arg("width"), nb::arg("height"), "Tint grayscale image red (for original overlay)");
    m.def("tint_blue", [process_grayscale](nb::bytes grayscale_buffer, int width, int height)
          { return process_grayscale(grayscale_buffer, width, height, 80, 80, 255, 235); }, nb::arg("grayscale_data"), nb::arg("width"), nb::arg("height"), "Tint grayscale image blue (for overlay comparison)");
    m.attr("__version__") = "1.0.0";
}
