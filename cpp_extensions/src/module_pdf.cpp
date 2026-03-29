#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/optional.h>
#include <nanobind/ndarray.h>
#include "pdf/pdf_renderer.hpp"
namespace nb = nanobind;
using namespace ost_pdf;
NB_MODULE(ost_pdf, m)
{
     m.doc() = "High-performance PDF rendering for OST Visualizer using PDFium";
     nb::class_<PageInfo>(m, "PageInfo",
                          "Resolved PDF page metadata. All dimensions in PDF points "
                          "(1/72 inch). intrinsic_rotation is the page's /Rotate entry "
                          "in degrees (0/90/180/270). effective_* match PDFium's "
                          "loaded page width/height, which are already rotation-aware.")
         .def_ro("media_width_pts", &PageInfo::media_width_pts,
                 "Unrotated mediabox width in points")
         .def_ro("media_height_pts", &PageInfo::media_height_pts,
                 "Unrotated mediabox height in points")
         .def_ro("crop_width_pts", &PageInfo::crop_width_pts,
                 "Crop/bounding-box width in points, or 0 if unavailable")
         .def_ro("crop_height_pts", &PageInfo::crop_height_pts,
                 "Crop/bounding-box height in points, or 0 if unavailable")
         .def_ro("effective_width_pts", &PageInfo::effective_width_pts,
                 "Loaded page width in points after PDFium applies page rotation")
         .def_ro("effective_height_pts", &PageInfo::effective_height_pts,
                 "Loaded page height in points after PDFium applies page rotation")
         .def_ro("intrinsic_rotation", &PageInfo::intrinsic_rotation,
                 "Page /Rotate value in degrees: 0, 90, 180, or 270")
         .def_ro("page_label", &PageInfo::page_label,
                 "Page label string from the document, or empty");
     nb::class_<RenderedPage>(m, "RenderedPage",
                              "A rendered PDF page as BGRA pixel data")
         .def_ro("width", &RenderedPage::width,
                 "Width in pixels")
         .def_ro("height", &RenderedPage::height,
                 "Height in pixels")
         .def_ro("stride", &RenderedPage::stride,
                 "Bytes per row (width * 4 for BGRA)")
         .def("to_bytes", [](const RenderedPage &page)
              { return nb::bytes(
                    reinterpret_cast<const char *>(page.pixels.data()),
                    page.pixels.size()); }, "Get pixel data as bytes (BGRA format)")
         .def("to_memoryview", [](const RenderedPage &page)
              {
                size_t shape[3] = {static_cast<size_t>(page.height), static_cast<size_t>(page.width), 4};
                int64_t strides[3] = {static_cast<int64_t>(page.stride), 4, 1};
                return nb::ndarray<nb::numpy, uint8_t>(
                    const_cast<uint8_t *>(page.pixels.data()), 3, shape, nb::handle(), strides); }, "Get pixel data as memoryview (BGRA format, shape: height x width x 4)");
     nb::class_<PDFRenderer>(m, "PDFRenderer",
                             "High-performance PDF renderer using PDFium")
         .def(nb::init<>(),
              "Create a new PDF renderer instance")
         .def("open", &PDFRenderer::open,
              nb::arg("path"),
              nb::call_guard<nb::gil_scoped_release>(),
              "Open a PDF file. Returns True on success.")
         .def("close", &PDFRenderer::close,
              nb::call_guard<nb::gil_scoped_release>(),
              "Close the currently open PDF")
         .def("is_open", &PDFRenderer::is_open,
              "Check if a PDF is currently open")
         .def("get_last_error", &PDFRenderer::get_last_error,
              "Get the last error message from PDFium")
         .def("page_count", &PDFRenderer::page_count,
              "Get the number of pages in the PDF")
         .def("page_size", &PDFRenderer::page_size,
              nb::arg("page_index"),
              nb::call_guard<nb::gil_scoped_release>(),
              "Get page size in points (1/72 inch). Returns (width, height) tuple.")
         .def("page_label", &PDFRenderer::page_label,
              nb::arg("page_index"),
              nb::call_guard<nb::gil_scoped_release>(),
              "Get the page label for a page. Returns empty string if no label.")
         .def("page_info", &PDFRenderer::page_info,
              nb::arg("page_index"),
              nb::call_guard<nb::gil_scoped_release>(),
              R"doc(
Resolve all PDF metadata for a single page in one call.
Returns a PageInfo with media_*_pts (raw mediabox), crop_*_pts
(page bounding/crop box), effective_*_pts (PDFium loaded page
dimensions, already rotation-aware), intrinsic_rotation in degrees,
and page_label. Returns None if the page index is invalid.
)doc")
         .def("all_page_info", &PDFRenderer::all_page_info,
              nb::call_guard<nb::gil_scoped_release>(),
              R"doc(
Return PageInfo for every page in the document, in order. Loads each
page once to read intrinsic rotation. Use this in preference to calling
page_info() in a Python loop.
)doc")
         .def("extract_path_segments", &PDFRenderer::extract_path_segments,
              nb::arg("page_index"),
              nb::call_guard<nb::gil_scoped_release>(),
              R"doc(
Extract straight PDF path segments from a page.
Coordinates are PDF user-space points with the origin at the bottom-left
of the loaded page. Curves, text outlines, and image content are ignored.
)doc")
         .def("render_page_region", &PDFRenderer::render_page_region,
              nb::arg("page_index"),
              nb::arg("scale"),
              nb::arg("tile_x"),
              nb::arg("tile_y"),
              nb::arg("tile_w"),
              nb::arg("tile_h"),
              nb::arg("rotation") = 0,
              nb::call_guard<nb::gil_scoped_release>(),
              R"doc(
Render a rectangular sub-region of a PDF page.
PDFium renders the full page geometry but clips output to the
tile_w × tile_h bitmap.  This avoids decoding off-screen pixels.
Args:
    page_index: Zero-based page index
    scale:      Render scale applied to the *full* page (same as render_page)
    tile_x:     Left pixel offset within the full scaled page
    tile_y:     Top  pixel offset within the full scaled page
    tile_w:     Output bitmap width  in pixels
    tile_h:     Output bitmap height in pixels
    rotation:   user-applied rotation in DEGREES (0/90/180/270).
                Out-of-range values are normalized to the nearest
                multiple of 90. PDF intrinsic rotation is already
                applied by FPDF_LoadPage; this is additive on top.
Returns:
    RenderedPage with dimensions (tile_w, tile_h), or None on failure
)doc")
         .def("render_page", &PDFRenderer::render_page,
              nb::arg("page_index"),
              nb::arg("scale") = 1.0f,
              nb::arg("rotation") = 0,
              nb::call_guard<nb::gil_scoped_release>(),
              R"doc(
Render a PDF page to BGRA pixels.
Args:
    page_index: Zero-based page index
    scale: Render scale (1.0 = 72 DPI, 2.0 = 144 DPI, etc.)
    rotation: user-applied rotation in DEGREES (0/90/180/270).
              Out-of-range values are normalized to the nearest
              multiple of 90. PDF intrinsic rotation is already
              applied by FPDF_LoadPage; this is additive on top.
Returns:
    RenderedPage object or None if rendering failed
Example:
    renderer = ost_pdf.PDFRenderer()
    if renderer.open("document.pdf"):
        page = renderer.render_page(0, scale=2.0)  # 144 DPI
        if page:
            # Use page.to_bytes() for QImage construction
            data = page.to_bytes()
            # Or page.to_memoryview() for numpy array
)doc");
     m.def("initialize", &initialize_pdfium,
           "Initialize PDFium library (called automatically on first use)");
     m.def("shutdown", &shutdown_pdfium,
           "Shutdown PDFium library (called automatically at program exit)");
     m.attr("__version__") = "1.0.0";
}
