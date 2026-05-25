#pragma once
#include <string>
#include <vector>
#include <array>
namespace ost_pdf_writer
{
    struct BluebeamPolygon
    {
        std::vector<std::array<double, 2>> vertices;
        std::vector<std::vector<std::array<double, 2>>> holes;
        std::string label;
        std::array<uint8_t, 3> stroke_color;
        std::array<uint8_t, 3> fill_color;
        double fill_opacity;
        double stroke_width;
        std::string author;
        std::string created_date;
        double area_sf;
        double scale_factor1;
        double scale_factor2;
        double depth;
        BluebeamPolygon()
            : stroke_color{255, 0, 0},
              fill_color{255, 0, 0},
              fill_opacity(0.5),
              stroke_width(1.0),
              author("OST Visualizer"),
              created_date(""),
              area_sf(0.0),
              scale_factor1(1.0),
              scale_factor2(1.0),
              depth(0.0) {}
    };
    std::string generate_bluebeam_polygon_dict(const BluebeamPolygon &polygon);
    std::string generate_page_measure_dict(double scale_factor1, double scale_factor2);
    std::string generate_annotation_measure_dict(double scale_factor1, double scale_factor2);
    std::string generate_helvetica_font_dict();
    std::string generate_appearance_stream_content(const BluebeamPolygon &polygon,
                                                   const std::string &area_text);
    std::string format_area_text(double area_sf);
    std::string generate_nm();
    struct BluebeamArrow
    {
        double x1;
        double y1;
        double x2;
        double y2;
        std::array<uint8_t, 3> color;
        double width;
        std::string author;
        std::string created_date;
        BluebeamArrow()
            : x1(0), y1(0), x2(0), y2(0),
              color{255, 0, 0},
              width(1.0),
              author("OST Visualizer") {}
    };
    std::string generate_bluebeam_arrow_dict(const BluebeamArrow &arrow);
    std::string generate_arrow_appearance_stream(const BluebeamArrow &arrow);
    struct BluebeamRect
    {
        double min_x;
        double min_y;
        double max_x;
        double max_y;
        std::array<uint8_t, 3> color;
        double width;
        std::string author;
        std::string created_date;
        BluebeamRect()
            : min_x(0), min_y(0), max_x(0), max_y(0),
              color{255, 0, 0},
              width(2.0),
              author("OST Visualizer") {}
    };
    std::string generate_bluebeam_rect_dict(const BluebeamRect &rect);
    std::string generate_rect_appearance_stream(const BluebeamRect &rect);
    struct BluebeamLine
    {
        double x1;
        double y1;
        double x2;
        double y2;
        std::array<uint8_t, 3> color;
        double width;
        std::string author;
        std::string created_date;
        BluebeamLine()
            : x1(0), y1(0), x2(0), y2(0),
              color{255, 0, 0},
              width(1.0),
              author("OST Visualizer") {}
    };
    std::string generate_bluebeam_line_dict(const BluebeamLine &line);
    std::string generate_line_appearance_stream(const BluebeamLine &line);
    struct BluebeamDimension
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
        std::string author;
        std::string created_date;
        BluebeamDimension()
            : x1(0), y1(0), x2(0), y2(0),
              color{255, 0, 0},
              width(1.0),
              content(""),
              font_size(10.0),
              scale_factor1(1.0),
              scale_factor2(1.0),
              author("OST Visualizer") {}
    };
    std::string generate_bluebeam_dimension_dict(const BluebeamDimension &dimension);
    std::string generate_dimension_appearance_stream(const BluebeamDimension &dimension);
    std::array<double, 4> compute_dimension_rect(const BluebeamDimension &dimension);
    struct BluebeamOval
    {
        double min_x;
        double min_y;
        double max_x;
        double max_y;
        std::array<uint8_t, 3> color;
        double width;
        std::string author;
        std::string created_date;
        BluebeamOval()
            : min_x(0), min_y(0), max_x(0), max_y(0),
              color{255, 0, 0},
              width(1.0),
              author("OST Visualizer") {}
    };
    std::string generate_bluebeam_oval_dict(const BluebeamOval &oval);
    std::string generate_oval_appearance_stream(const BluebeamOval &oval);
    struct BluebeamPolygonAnnot
    {
        std::vector<std::array<double, 2>> vertices;
        std::array<uint8_t, 3> color;
        double width;
        std::string author;
        std::string created_date;
        bool is_cloud;
        BluebeamPolygonAnnot()
            : color{255, 0, 0},
              width(1.0),
              author("OST Visualizer"),
              is_cloud(false) {}
    };
    std::string generate_bluebeam_polygon_annot_dict(const BluebeamPolygonAnnot &poly);
    std::string generate_polygon_annot_appearance_stream(const BluebeamPolygonAnnot &poly);
    struct BluebeamInk
    {
        std::vector<std::vector<std::array<double, 2>>> strokes;
        std::array<uint8_t, 3> color;
        double width;
        std::string author;
        std::string created_date;
        BluebeamInk()
            : color{255, 0, 0},
              width(1.0),
              author("OST Visualizer") {}
    };
    std::string generate_bluebeam_ink_dict(const BluebeamInk &ink);
    std::string generate_ink_appearance_stream(const BluebeamInk &ink);
    struct BluebeamText
    {
        double min_x;
        double min_y;
        double max_x;
        double max_y;
        std::string content;
        double font_size;
        std::array<uint8_t, 3> color;
        std::string text_align;
        std::string author;
        std::string created_date;
        BluebeamText()
            : min_x(0), min_y(0), max_x(0), max_y(0),
              font_size(12.0),
              color{0, 0, 0},
              text_align("left"),
              author("OST Visualizer") {}
    };
    std::string generate_bluebeam_text_dict(const BluebeamText &text);
    std::string generate_text_appearance_stream(const BluebeamText &text);
}
