#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/array.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/pair.h>
#include "pdf/pdf_writer.hpp"
namespace nb = nanobind;
using namespace ost_pdf_writer;
NB_MODULE(ost_pdf_writer, m)
{
        m.doc() = "High-performance PDF manipulation for OST Visualizer using QPDF";
        nb::class_<PDFWriter::AnnotationCaptionData>(m, "AnnotationCaptionData",
                                                     "Resolved text for a measurement annotation caption")
            .def(nb::init<>())
            .def_rw("lines", &PDFWriter::AnnotationCaptionData::lines,
                    "Caption lines in Bluebeam display order")
            .def_rw("label", &PDFWriter::AnnotationCaptionData::label,
                    "Resolved Bluebeam annotation label")
            .def_rw("measurement_types",
                    &PDFWriter::AnnotationCaptionData::measurement_types,
                    "Bluebeam MeasurementTypes bit mask");
        nb::class_<PDFWriter::PolygonAnnotationData>(m, "PolygonAnnotationData",
                                                     "Data for a single polygon annotation with measurement")
            .def(nb::init<>())
            .def_rw("vertices", &PDFWriter::PolygonAnnotationData::vertices,
                    "List of (x, y) coordinates in PDF points")
            .def_rw("holes", &PDFWriter::PolygonAnnotationData::holes,
                    "List of cutout polygons, each a list of (x, y) coordinates")
            .def_rw("label", &PDFWriter::PolygonAnnotationData::label,
                    "Text label for the annotation")
            .def_rw("color", &PDFWriter::PolygonAnnotationData::color,
                    "RGB color as [r, g, b] (0-255)")
            .def_rw("fill_opacity", &PDFWriter::PolygonAnnotationData::fill_opacity,
                    "Fill opacity from 0.0 to 1.0")
            .def_rw("area_sf", &PDFWriter::PolygonAnnotationData::area_sf,
                    "Area in square feet (0 = no measurement)")
            .def_rw("scale_factor1", &PDFWriter::PolygonAnnotationData::scale_factor1,
                    "Plan scale factor (e.g., 0.09375 for 3/32\")")
            .def_rw("scale_factor2", &PDFWriter::PolygonAnnotationData::scale_factor2,
                    "Inches (e.g., 12)")
            .def_rw("depth", &PDFWriter::PolygonAnnotationData::depth,
                    "Depth/thickness in feet (0 = none)")
            .def_rw("caption", &PDFWriter::PolygonAnnotationData::caption,
                    "Resolved measurement caption data");
        nb::class_<PDFWriter::ArrowAnnotationData>(m, "ArrowAnnotationData",
                                                   "Data for a single arrow annotation")
            .def(nb::init<>())
            .def_rw("x1", &PDFWriter::ArrowAnnotationData::x1,
                    "Start X coordinate in PDF points")
            .def_rw("y1", &PDFWriter::ArrowAnnotationData::y1,
                    "Start Y coordinate in PDF points")
            .def_rw("x2", &PDFWriter::ArrowAnnotationData::x2,
                    "End X coordinate in PDF points")
            .def_rw("y2", &PDFWriter::ArrowAnnotationData::y2,
                    "End Y coordinate in PDF points")
            .def_rw("color", &PDFWriter::ArrowAnnotationData::color,
                    "RGB color as [r, g, b] (0-255)")
            .def_rw("width", &PDFWriter::ArrowAnnotationData::width,
                    "Line width in PDF points");
        nb::class_<PDFWriter::RectAnnotationData>(m, "RectAnnotationData",
                                                  "Data for a single rectangle annotation")
            .def(nb::init<>())
            .def_rw("min_x", &PDFWriter::RectAnnotationData::min_x,
                    "Minimum X coordinate in PDF points")
            .def_rw("min_y", &PDFWriter::RectAnnotationData::min_y,
                    "Minimum Y coordinate in PDF points")
            .def_rw("max_x", &PDFWriter::RectAnnotationData::max_x,
                    "Maximum X coordinate in PDF points")
            .def_rw("max_y", &PDFWriter::RectAnnotationData::max_y,
                    "Maximum Y coordinate in PDF points")
            .def_rw("color", &PDFWriter::RectAnnotationData::color,
                    "RGB color as [r, g, b] (0-255)")
            .def_rw("width", &PDFWriter::RectAnnotationData::width,
                    "Border width in PDF points");
        nb::class_<PDFWriter::LineAnnotationData>(m, "LineAnnotationData",
                                                  "Data for a single line annotation")
            .def(nb::init<>())
            .def_rw("x1", &PDFWriter::LineAnnotationData::x1,
                    "Start X coordinate in PDF points")
            .def_rw("y1", &PDFWriter::LineAnnotationData::y1,
                    "Start Y coordinate in PDF points")
            .def_rw("x2", &PDFWriter::LineAnnotationData::x2,
                    "End X coordinate in PDF points")
            .def_rw("y2", &PDFWriter::LineAnnotationData::y2,
                    "End Y coordinate in PDF points")
            .def_rw("color", &PDFWriter::LineAnnotationData::color,
                    "RGB color as [r, g, b] (0-255)")
            .def_rw("width", &PDFWriter::LineAnnotationData::width,
                    "Line width in PDF points");
        nb::class_<PDFWriter::DimensionAnnotationData>(m, "DimensionAnnotationData",
                                                       "Data for a line dimension annotation")
            .def(nb::init<>())
            .def_rw("x1", &PDFWriter::DimensionAnnotationData::x1,
                    "Start X coordinate in PDF points")
            .def_rw("y1", &PDFWriter::DimensionAnnotationData::y1,
                    "Start Y coordinate in PDF points")
            .def_rw("x2", &PDFWriter::DimensionAnnotationData::x2,
                    "End X coordinate in PDF points")
            .def_rw("y2", &PDFWriter::DimensionAnnotationData::y2,
                    "End Y coordinate in PDF points")
            .def_rw("color", &PDFWriter::DimensionAnnotationData::color,
                    "RGB color as [r, g, b] (0-255)")
            .def_rw("width", &PDFWriter::DimensionAnnotationData::width,
                    "Line width in PDF points")
            .def_rw("content", &PDFWriter::DimensionAnnotationData::content,
                    "Formatted measurement label")
            .def_rw("font_size", &PDFWriter::DimensionAnnotationData::font_size,
                    "Font size in PDF points")
            .def_rw("scale_factor1", &PDFWriter::DimensionAnnotationData::scale_factor1,
                    "Plan scale factor for measurement metadata")
            .def_rw("scale_factor2", &PDFWriter::DimensionAnnotationData::scale_factor2,
                    "Plan scale denominator for measurement metadata");
        nb::class_<PDFWriter::OvalAnnotationData>(m, "OvalAnnotationData",
                                                  "Data for a single oval/circle annotation")
            .def(nb::init<>())
            .def_rw("center_x", &PDFWriter::OvalAnnotationData::center_x,
                    "Ellipse center X coordinate in PDF points")
            .def_rw("center_y", &PDFWriter::OvalAnnotationData::center_y,
                    "Ellipse center Y coordinate in PDF points")
            .def_rw("x_axis_dx", &PDFWriter::OvalAnnotationData::x_axis_dx,
                    "Local X radius vector X component in PDF points")
            .def_rw("x_axis_dy", &PDFWriter::OvalAnnotationData::x_axis_dy,
                    "Local X radius vector Y component in PDF points")
            .def_rw("y_axis_dx", &PDFWriter::OvalAnnotationData::y_axis_dx,
                    "Local Y radius vector X component in PDF points")
            .def_rw("y_axis_dy", &PDFWriter::OvalAnnotationData::y_axis_dy,
                    "Local Y radius vector Y component in PDF points")
            .def_rw("color", &PDFWriter::OvalAnnotationData::color,
                    "RGB color as [r, g, b] (0-255)")
            .def_rw("width", &PDFWriter::OvalAnnotationData::width,
                    "Border width in PDF points");
        nb::class_<PDFWriter::PolygonAnnotationAnnotData>(m, "PolygonAnnotationAnnotData",
                                                          "Data for a polygon or cloud annotation")
            .def(nb::init<>())
            .def_rw("vertices", &PDFWriter::PolygonAnnotationAnnotData::vertices,
                    "List of (x, y) coordinates in PDF points")
            .def_rw("color", &PDFWriter::PolygonAnnotationAnnotData::color,
                    "RGB color as [r, g, b] (0-255)")
            .def_rw("width", &PDFWriter::PolygonAnnotationAnnotData::width,
                    "Line width in PDF points")
            .def_rw("is_cloud", &PDFWriter::PolygonAnnotationAnnotData::is_cloud,
                    "True if this is a cloud annotation, false for regular polygon");
        nb::class_<PDFWriter::InkAnnotationData>(m, "InkAnnotationData",
                                                 "Data for an ink/pen annotation with multiple strokes")
            .def(nb::init<>())
            .def_rw("strokes", &PDFWriter::InkAnnotationData::strokes,
                    "List of stroke paths, each a list of (x, y) coordinates in PDF points")
            .def_rw("color", &PDFWriter::InkAnnotationData::color,
                    "RGB color as [r, g, b] (0-255)")
            .def_rw("width", &PDFWriter::InkAnnotationData::width,
                    "Stroke width in PDF points");
        nb::class_<PDFWriter::TextAnnotationData>(m, "TextAnnotationData",
                                                  "Data for a FreeText (text box) annotation")
            .def(nb::init<>())
            .def_rw("min_x", &PDFWriter::TextAnnotationData::min_x,
                    "Minimum X coordinate (left) in PDF points")
            .def_rw("min_y", &PDFWriter::TextAnnotationData::min_y,
                    "Minimum Y coordinate (bottom) in PDF points")
            .def_rw("max_x", &PDFWriter::TextAnnotationData::max_x,
                    "Maximum X coordinate (right) in PDF points")
            .def_rw("max_y", &PDFWriter::TextAnnotationData::max_y,
                    "Maximum Y coordinate (top) in PDF points")
            .def_rw("content", &PDFWriter::TextAnnotationData::content,
                    "Text content of the annotation")
            .def_rw("font_size", &PDFWriter::TextAnnotationData::font_size,
                    "Font size in PDF points")
            .def_rw("color", &PDFWriter::TextAnnotationData::color,
                    "RGB font color as [r, g, b] (0-255)")
            .def_rw("text_align", &PDFWriter::TextAnnotationData::text_align,
                    "Text alignment: 'left', 'center', or 'right'");
        nb::class_<PDFWriter::HighlightAnnotationData>(m, "HighlightAnnotationData",
                                                       "Data for a Bluebeam-style ink highlighter annotation")
            .def(nb::init<>())
            .def_rw("strokes", &PDFWriter::HighlightAnnotationData::strokes,
                    "List of highlighter stroke paths, each a list of (x, y) coordinates in PDF points")
            .def_rw("color", &PDFWriter::HighlightAnnotationData::color,
                    "RGB highlight color as [r, g, b] (0-255)")
            .def_rw("width", &PDFWriter::HighlightAnnotationData::width,
                    "Highlighter stroke width in PDF points")
            .def_rw("opacity", &PDFWriter::HighlightAnnotationData::opacity,
                    "Highlight opacity from 0.0 to 1.0")
            .def_rw("content", &PDFWriter::HighlightAnnotationData::content,
                    "Optional highlight contents text");
        nb::class_<PDFWriter::PageExportData>(m, "PageExportData",
                                              "Data for exporting a single page with takeoffs")
            .def(nb::init<>())
            .def_rw("source_pdf", &PDFWriter::PageExportData::source_pdf,
                    "Path to source PDF file (empty for blank pages)")
            .def_rw("page_index", &PDFWriter::PageExportData::page_index,
                    "Zero-based page index to copy")
            .def_rw("takeoffs", &PDFWriter::PageExportData::takeoffs,
                    "List of area takeoff polygons (PolygonAnnotationData) for this page")
            .def_rw("arrows", &PDFWriter::PageExportData::arrows,
                    "List of arrow annotations (ArrowAnnotationData) for this page")
            .def_rw("rects", &PDFWriter::PageExportData::rects,
                    "List of rectangle annotations (RectAnnotationData) for this page")
            .def_rw("lines", &PDFWriter::PageExportData::lines,
                    "List of line annotations (LineAnnotationData) for this page")
            .def_rw("dimensions", &PDFWriter::PageExportData::dimensions,
                    "List of line dimension annotations (DimensionAnnotationData) for this page")
            .def_rw("ovals", &PDFWriter::PageExportData::ovals,
                    "List of oval annotations (OvalAnnotationData) for this page")
            .def_rw("polygons", &PDFWriter::PageExportData::polygons,
                    "List of polygon/cloud annotations (PolygonAnnotationAnnotData) for this page")
            .def_rw("inks", &PDFWriter::PageExportData::inks,
                    "List of ink/pen annotations (InkAnnotationData) for this page")
            .def_rw("texts", &PDFWriter::PageExportData::texts,
                    "List of text box annotations (TextAnnotationData) for this page")
            .def_rw("highlights", &PDFWriter::PageExportData::highlights,
                    "List of highlight annotations (HighlightAnnotationData) for this page")
            .def_rw("page_width", &PDFWriter::PageExportData::page_width,
                    "Page width in points (for blank pages, default 612)")
            .def_rw("page_height", &PDFWriter::PageExportData::page_height,
                    "Page height in points (for blank pages, default 792)")
            .def_rw("rotation", &PDFWriter::PageExportData::rotation,
                    "Page rotation in degrees (0, 90, 180, 270) for blank pages")
            .def_rw("is_blank", &PDFWriter::PageExportData::is_blank,
                    "True if this is a blank page (no source PDF)");
        nb::class_<PDFWriter>(m, "PDFWriter",
                              "PDF writer and annotation manager")
            .def(nb::init<>(),
                 "Create a new PDF writer instance")
            .def("copy_page", &PDFWriter::copy_page,
                 nb::arg("source_pdf"),
                 nb::arg("page_index"),
                 nb::arg("output_pdf"),
                 R"doc(
Copy a single page from source PDF to a new PDF file.
Args:
    source_pdf: Path to source PDF file
    page_index: Zero-based page index to copy
    output_pdf: Path to output PDF file
Returns:
    True if successful, False otherwise
Example:
    writer = PDFWriter()
    if writer.copy_page("input.pdf", 0, "output.pdf"):
        print("Page copied successfully")
    else:
        print(f"Error: {writer.get_last_error()}")
)doc")
            .def("add_polygon_annotation", &PDFWriter::add_polygon_annotation,
                 nb::arg("pdf_path"),
                 nb::arg("vertices"),
                 nb::arg("label"),
                 nb::arg("color"),
                 nb::arg("fill_opacity"),
                 R"doc(
Add a Bluebeam-compatible polygon annotation to a PDF.
Args:
    pdf_path: Path to PDF file to modify
    vertices: List of (x, y) tuples in PDF points (1/72 inch)
    label: Text label for the annotation
    color: RGB color as [r, g, b] where each component is 0-255
    fill_opacity: Fill opacity from 0.0 (transparent) to 1.0 (opaque)
Returns:
    True if successful, False otherwise
Example:
    writer = PDFWriter()
    vertices = [(100, 100), (200, 100), (200, 200), (100, 200)]
    if writer.add_polygon_annotation(
        "output.pdf",
        vertices,
        "Area 1",
        [255, 0, 0],  # Red
        0.5
    ):
        print("Annotation added successfully")
)doc")
            .def("add_polygon_annotations_batch", &PDFWriter::add_polygon_annotations_batch,
                 nb::arg("pdf_path"),
                 nb::arg("annotations"),
                 R"doc(
Add multiple polygon annotations to a PDF in a single operation.
This is more efficient than calling add_polygon_annotation multiple times,
as it opens the PDF once, adds all annotations, and writes once.
Args:
    pdf_path: Path to PDF file to modify
    annotations: List of PolygonAnnotationData objects
Returns:
    True if successful, False otherwise
Example:
    writer = PDFWriter()
    annotations = []
    # First annotation
    annot1 = PolygonAnnotationData()
    annot1.vertices = [(100, 100), (200, 100), (200, 200), (100, 200)]
    annot1.label = "Area 1"
    annot1.color = [255, 0, 0]  # Red
    annot1.fill_opacity = 0.5
    annotations.append(annot1)
    # Second annotation
    annot2 = PolygonAnnotationData()
    annot2.vertices = [(300, 300), (400, 300), (400, 400), (300, 400)]
    annot2.label = "Area 2"
    annot2.color = [0, 0, 255]  # Blue
    annot2.fill_opacity = 0.5
    annotations.append(annot2)
    if writer.add_polygon_annotations_batch("output.pdf", annotations):
        print("All annotations added successfully")
)doc")
            .def("export_page_with_annotations", &PDFWriter::export_page_with_annotations,
                 nb::arg("source_pdf"),
                 nb::arg("page_index"),
                 nb::arg("output_pdf"),
                 nb::arg("annotations"),
                 R"doc(
Export a page from source PDF with annotations in a single operation.
This combines copy_page and add_polygon_annotations_batch, avoiding file
locking issues by keeping the PDF open throughout the operation.
Args:
    source_pdf: Path to source PDF file
    page_index: Zero-based page index to copy
    output_pdf: Path to output PDF file
    annotations: List of PolygonAnnotationData objects to add
Returns:
    True if successful, False otherwise
Example:
    writer = PDFWriter()
    annotations = []
    annot = PolygonAnnotationData()
    annot.vertices = [(100, 100), (200, 100), (200, 200), (100, 200)]
    annot.label = "Area 1"
    annot.color = [255, 0, 0]  # Red
    annot.fill_opacity = 0.5
    annotations.append(annot)
    if writer.export_page_with_annotations("input.pdf", 0, "output.pdf", annotations):
        print("Page exported with annotations successfully")
)doc")
            .def("merge_pages_with_annotations", &PDFWriter::merge_pages_with_annotations,
                 nb::arg("pages"),
                 nb::arg("output_pdf"),
                 R"doc(
Merge multiple pages from different PDFs into a single output PDF.
Each page can have its own set of area takeoff polygons and arrow annotations.
This is useful for exporting multiple pages with takeoff measurements in a single operation.
Args:
    pages: List of PageExportData objects, each containing:
        - source_pdf: Path to source PDF file
        - page_index: Zero-based page index to copy
        - takeoffs: List of PolygonAnnotationData objects (area takeoffs) for this page
        - arrows: List of ArrowAnnotationData objects for this page
    output_pdf: Path to output PDF file
Returns:
    True if successful, False otherwise
Example:
    writer = PDFWriter()
    # First page with area takeoff
    takeoff1 = PolygonAnnotationData()
    takeoff1.vertices = [(100, 100), (200, 100), (200, 200), (100, 200)]
    takeoff1.label = "Area 1"
    takeoff1.color = [255, 0, 0]
    takeoff1.fill_opacity = 0.5
    # First page with arrow
    arrow1 = ArrowAnnotationData()
    arrow1.x1 = 100
    arrow1.y1 = 100
    arrow1.x2 = 200
    arrow1.y2 = 200
    arrow1.color = [255, 0, 0]
    arrow1.width = 1.0
    page1 = PageExportData()
    page1.source_pdf = "plan1.pdf"
    page1.page_index = 0
    page1.takeoffs = [takeoff1]
    page1.arrows = [arrow1]
    if writer.merge_pages_with_annotations([page1], "merged.pdf"):
        print("Pages merged successfully")
)doc")
            .def("get_page_sizes", &PDFWriter::get_page_sizes,
                 nb::arg("pdf_path"),
                 R"doc(
Get the actual page sizes and MediaBox origins from a PDF file using QPDF.
Returns the true visible dimensions (urx-llx, ury-lly) and the page origin
(llx, lly), which are needed for correct coordinate transformations.
Args:
    pdf_path: Path to the PDF file
Returns:
    List of [width, height, llx, lly] arrays for each page in the PDF,
    where width = urx - llx and height = ury - lly from the /MediaBox entry.
Example:
    writer = PDFWriter()
    sizes = writer.get_page_sizes("plan.pdf")
    for i, s in enumerate(sizes):
        print(f"Page {i}: {s[0]}x{s[1]} points, origin ({s[2]}, {s[3]})")
)doc")
            .def("get_last_error", &PDFWriter::get_last_error,
                 "Get the last error message from a failed operation");
        m.attr("__version__") = "1.0.0";
}
