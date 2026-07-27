#pragma once
#include <string>
#include <vector>
#include <array>
#include <cstdint>
#include <optional>
#include "bluebeam_annotation.hpp"
namespace ost_pdf_writer
{
    class PDFWriter
    {
    public:
        PDFWriter();
        ~PDFWriter();
        using AnnotationCaptionData = BluebeamCaption;
        bool copy_page(const std::string &source_pdf,
                       int page_index,
                       const std::string &output_pdf);
        struct PolygonAnnotationData
        {
            std::vector<std::array<double, 2>> vertices;
            std::vector<std::vector<std::array<double, 2>>> holes;
            std::string label;
            std::array<uint8_t, 3> color;
            double fill_opacity;
            double area_sf;
            double scale_factor1;
            double scale_factor2;
            double depth;
            AnnotationCaptionData caption;
        };
        bool add_polygon_annotation(const std::string &pdf_path,
                                    const std::vector<std::array<double, 2>> &vertices,
                                    const std::string &label,
                                    const std::array<uint8_t, 3> &color,
                                    double fill_opacity);
        bool add_polygon_annotations_batch(const std::string &pdf_path,
                                           const std::vector<PolygonAnnotationData> &annotations);
        bool export_page_with_annotations(const std::string &source_pdf,
                                          int page_index,
                                          const std::string &output_pdf,
                                          const std::vector<PolygonAnnotationData> &annotations);
        struct ArrowAnnotationData
        {
            double x1;
            double y1;
            double x2;
            double y2;
            std::array<uint8_t, 3> color;
            double width;
        };
        struct RectAnnotationData
        {
            double min_x;
            double min_y;
            double max_x;
            double max_y;
            std::array<uint8_t, 3> color;
            double width;
        };
        struct LineAnnotationData
        {
            double x1;
            double y1;
            double x2;
            double y2;
            std::array<uint8_t, 3> color;
            double width;
        };
        struct DimensionAnnotationData
        {
            double x1;
            double y1;
            double x2;
            double y2;
            std::array<uint8_t, 3> color;
            double width;
            std::string content;
            double font_size;
            double scale_factor1;
            double scale_factor2;
        };
        struct OvalAnnotationData
        {
            double min_x;
            double min_y;
            double max_x;
            double max_y;
            std::array<uint8_t, 3> color;
            double width;
        };
        struct PolygonAnnotationAnnotData
        {
            std::vector<std::array<double, 2>> vertices;
            std::array<uint8_t, 3> color;
            double width;
            bool is_cloud;
        };
        struct InkAnnotationData
        {
            std::vector<std::vector<std::array<double, 2>>> strokes;
            std::array<uint8_t, 3> color;
            double width;
        };
        struct TextAnnotationData
        {
            double min_x;
            double min_y;
            double max_x;
            double max_y;
            std::string content;
            double font_size;
            std::array<uint8_t, 3> color;
            std::string text_align;
        };
        struct HighlightAnnotationData
        {
            std::vector<std::vector<std::array<double, 2>>> strokes;
            std::array<uint8_t, 3> color;
            double width;
            double opacity;
            std::string content;
        };
        struct PageExportData
        {
            std::string source_pdf;
            int page_index;
            std::vector<PolygonAnnotationData> takeoffs;
            std::vector<ArrowAnnotationData> arrows;
            std::vector<RectAnnotationData> rects;
            std::vector<LineAnnotationData> lines;
            std::vector<DimensionAnnotationData> dimensions;
            std::vector<OvalAnnotationData> ovals;
            std::vector<PolygonAnnotationAnnotData> polygons;
            std::vector<InkAnnotationData> inks;
            std::vector<TextAnnotationData> texts;
            std::vector<HighlightAnnotationData> highlights;
            double page_width;
            double page_height;
            int rotation;
            bool is_blank;
            PageExportData() : source_pdf(""), page_index(0), page_width(612.0), page_height(792.0), rotation(0), is_blank(false) {}
        };
        bool merge_pages_with_annotations(const std::vector<PageExportData> &pages,
                                          const std::string &output_pdf);
        std::string get_last_error() const { return last_error_; }
        std::vector<std::array<double, 4>> get_page_sizes(const std::string &pdf_path);

    private:
        std::string last_error_;
        void set_error(const std::string &error);
    };
}
