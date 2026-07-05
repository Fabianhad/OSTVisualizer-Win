#include "pdf_writer.hpp"
#include "bluebeam_annotation.hpp"
#include <qpdf/QPDF.hh>
#include <qpdf/QPDFWriter.hh>
#include <qpdf/QPDFPageDocumentHelper.hh>
#include <qpdf/QPDFPageObjectHelper.hh>
#include <qpdf/QUtil.hh>
#include <sstream>
#include <iostream>
#include <iomanip>
#include <chrono>
#include <algorithm>
namespace ost_pdf_writer
{
    static std::string get_pdf_date()
    {
        auto now = std::chrono::system_clock::now();
        std::time_t tt = std::chrono::system_clock::to_time_t(now);
        std::tm tm{};
#ifdef _WIN32
        localtime_s(&tm, &tt);
#else
        localtime_r(&tt, &tm);
#endif
        std::ostringstream oss;
        oss << std::setfill('0')
            << "D:"
            << std::setw(4) << (tm.tm_year + 1900)
            << std::setw(2) << (tm.tm_mon + 1)
            << std::setw(2) << tm.tm_mday
            << std::setw(2) << tm.tm_hour
            << std::setw(2) << tm.tm_min
            << std::setw(2) << tm.tm_sec;
        char tz_name[6];
        std::strftime(tz_name, sizeof(tz_name), "%z", &tm);
        if (tz_name[0] == '\0' || tz_name[0] == 'Z')
        {
            oss << "Z";
        }
        else
        {
            oss << tz_name[0] << tz_name[1] << tz_name[2] << "'" << tz_name[3] << tz_name[4] << "'";
        }
        return oss.str();
    }
    static QPDFObjectHandle get_or_create_annots(QPDFObjectHandle &page_dict)
    {
        QPDFObjectHandle annots = page_dict.getKey("/Annots");
        if (annots.isNull())
        {
            annots = QPDFObjectHandle::newArray();
            page_dict.replaceKey("/Annots", annots);
        }
        return annots;
    }
    static void initialize_pdf_metadata(QPDF &output)
    {
        output.getRoot().replaceKey("/Version", QPDFObjectHandle::newName("/1.7"));
        QPDFObjectHandle info = QPDFObjectHandle::newDictionary();
        info.replaceKey("/ModDate", QPDFObjectHandle::newString(get_pdf_date().c_str()));
        output.getTrailer().replaceKey("/Info", output.makeIndirectObject(info));
    }
    static std::array<double, 4> compute_bbox(
        const std::vector<std::array<double, 2>> &vertices)
    {
        double min_x = vertices[0][0], min_y = vertices[0][1];
        double max_x = vertices[0][0], max_y = vertices[0][1];
        for (const auto &v : vertices)
        {
            if (v[0] < min_x)
                min_x = v[0];
            if (v[0] > max_x)
                max_x = v[0];
            if (v[1] < min_y)
                min_y = v[1];
            if (v[1] > max_y)
                max_y = v[1];
        }
        return {min_x, min_y, max_x, max_y};
    }
    static std::array<double, 4> compute_bbox_with_holes(
        const std::vector<std::array<double, 2>> &vertices,
        const std::vector<std::vector<std::array<double, 2>>> &holes)
    {
        auto bb = compute_bbox(vertices);
        for (const auto &hole : holes)
        {
            for (const auto &v : hole)
            {
                if (v[0] < bb[0])
                    bb[0] = v[0];
                if (v[0] > bb[2])
                    bb[2] = v[0];
                if (v[1] < bb[1])
                    bb[1] = v[1];
                if (v[1] > bb[3])
                    bb[3] = v[1];
            }
        }
        return bb;
    }
    static std::array<double, 4> compute_bbox_strokes(
        const std::vector<std::vector<std::array<double, 2>>> &strokes)
    {
        double min_x = strokes[0][0][0], min_y = strokes[0][0][1];
        double max_x = strokes[0][0][0], max_y = strokes[0][0][1];
        for (const auto &stroke : strokes)
        {
            for (const auto &pt : stroke)
            {
                if (pt[0] < min_x)
                    min_x = pt[0];
                if (pt[0] > max_x)
                    max_x = pt[0];
                if (pt[1] < min_y)
                    min_y = pt[1];
                if (pt[1] > max_y)
                    max_y = pt[1];
            }
        }
        return {min_x, min_y, max_x, max_y};
    }
    static void attach_appearance_stream(
        QPDF &output,
        QPDFObjectHandle &annot_obj,
        const std::string &ap_content,
        double x1, double y1, double x2, double y2,
        QPDFObjectHandle extra_res = QPDFObjectHandle::newNull())
    {
        QPDFObjectHandle ap_stream_obj = QPDFObjectHandle::newStream(&output, ap_content);
        QPDFObjectHandle ap_stream_dict = ap_stream_obj.getDict();
        ap_stream_dict.replaceKey("/Type", QPDFObjectHandle::newName("/XObject"));
        ap_stream_dict.replaceKey("/Subtype", QPDFObjectHandle::newName("/Form"));
        ap_stream_dict.replaceKey("/FormType", QPDFObjectHandle::newInteger(1));
        QPDFObjectHandle ap_bbox = QPDFObjectHandle::newArray();
        ap_bbox.appendItem(QPDFObjectHandle::newReal(x1));
        ap_bbox.appendItem(QPDFObjectHandle::newReal(y1));
        ap_bbox.appendItem(QPDFObjectHandle::newReal(x2));
        ap_bbox.appendItem(QPDFObjectHandle::newReal(y2));
        ap_stream_dict.replaceKey("/BBox", ap_bbox);
        QPDFObjectHandle ap_resources = QPDFObjectHandle::newDictionary();
        QPDFObjectHandle procset = QPDFObjectHandle::newArray();
        procset.appendItem(QPDFObjectHandle::newName("/PDF"));
        ap_resources.replaceKey("/ProcSet", procset);
        if (!extra_res.isNull())
        {
            for (const auto &k : extra_res.getKeys())
                ap_resources.replaceKey(k, extra_res.getKey(k));
        }
        ap_stream_dict.replaceKey("/Resources", ap_resources);
        QPDFObjectHandle matrix = QPDFObjectHandle::newArray();
        matrix.appendItem(QPDFObjectHandle::newInteger(1));
        matrix.appendItem(QPDFObjectHandle::newInteger(0));
        matrix.appendItem(QPDFObjectHandle::newInteger(0));
        matrix.appendItem(QPDFObjectHandle::newInteger(1));
        matrix.appendItem(QPDFObjectHandle::newReal(-x1));
        matrix.appendItem(QPDFObjectHandle::newReal(-y1));
        ap_stream_dict.replaceKey("/Matrix", matrix);
        QPDFObjectHandle ap_stream_ref = output.makeIndirectObject(ap_stream_obj);
        QPDFObjectHandle ap_dict = QPDFObjectHandle::newDictionary();
        ap_dict.replaceKey("/N", ap_stream_ref);
        annot_obj.replaceKey("/AP", ap_dict);
    }
    static bool has_valid_measure_scale(double scale_factor1, double scale_factor2)
    {
        return scale_factor1 > 0.0 && scale_factor2 > 0.0;
    }
    static QPDFObjectHandle make_page_measure_ref(QPDF &output,
                                                  double scale_factor1,
                                                  double scale_factor2)
    {
        std::string measure_str = generate_page_measure_dict(scale_factor1, scale_factor2);
        QPDFObjectHandle measure_obj = QPDFObjectHandle::parse(&output, measure_str);
        return output.makeIndirectObject(measure_obj);
    }
    static QPDFObjectHandle make_viewport_array(QPDF &output,
                                                QPDFPageObjectHelper &page,
                                                QPDFObjectHandle measure_ref)
    {
        QPDFObjectHandle media_box = page.getAttribute("/MediaBox", false);
        double page_width = media_box.getArrayItem(2).getNumericValue() - media_box.getArrayItem(0).getNumericValue();
        double page_height = media_box.getArrayItem(3).getNumericValue() - media_box.getArrayItem(1).getNumericValue();
        QPDFObjectHandle viewport = QPDFObjectHandle::newDictionary();
        viewport.replaceKey("/Type", QPDFObjectHandle::newName("/Viewport"));
        QPDFObjectHandle bbox = QPDFObjectHandle::newArray();
        bbox.appendItem(QPDFObjectHandle::newInteger(0));
        bbox.appendItem(QPDFObjectHandle::newInteger(0));
        bbox.appendItem(QPDFObjectHandle::newReal(page_width));
        bbox.appendItem(QPDFObjectHandle::newReal(page_height));
        viewport.replaceKey("/BBox", bbox);
        viewport.replaceKey("/Measure", measure_ref);
        viewport.replaceKey("/NM", QPDFObjectHandle::newString(generate_nm().c_str()));
        QPDFObjectHandle viewport_indirect = output.makeIndirectObject(viewport);
        QPDFObjectHandle vp_array = QPDFObjectHandle::newArray();
        vp_array.appendItem(viewport_indirect);
        return vp_array;
    }
    static void replace_page_viewport_measure(QPDF &output,
                                              QPDFPageObjectHelper &page,
                                              QPDFObjectHandle measure_ref)
    {
        page.getObjectHandle().replaceKey(
            "/VP", make_viewport_array(output, page, measure_ref));
    }
    static void ensure_page_viewport_measure(QPDF &output,
                                             QPDFPageObjectHelper &page,
                                             double scale_factor1,
                                             double scale_factor2)
    {
        QPDFObjectHandle page_dict = page.getObjectHandle();
        if (!has_valid_measure_scale(scale_factor1, scale_factor2) ||
            !page_dict.getKey("/VP").isNull())
        {
            return;
        }
        replace_page_viewport_measure(
            output, page, make_page_measure_ref(output, scale_factor1, scale_factor2));
    }
    PDFWriter::PDFWriter() : last_error_("") {}
    PDFWriter::~PDFWriter() {}
    void PDFWriter::set_error(const std::string &error)
    {
        last_error_ = error;
    }
    bool PDFWriter::copy_page(const std::string &source_pdf,
                              int page_index,
                              const std::string &output_pdf)
    {
        try
        {
            QPDF source;
            source.processFile(source_pdf.c_str());
            QPDFPageDocumentHelper source_pages(source);
            std::vector<QPDFPageObjectHelper> pages = source_pages.getAllPages();
            if (page_index < 0 || page_index >= static_cast<int>(pages.size()))
            {
                set_error("Page index out of range: " + std::to_string(page_index));
                return false;
            }
            QPDF output;
            output.emptyPDF();
            QPDFPageDocumentHelper output_pages(output);
            QPDFPageObjectHelper selected_page = pages[page_index];
            output_pages.addPage(selected_page.getObjectHandle(), false);
            QPDFWriter writer(output, output_pdf.c_str());
            writer.setStaticID(true);
            writer.write();
            return true;
        }
        catch (const std::exception &e)
        {
            set_error(std::string("Failed to copy page: ") + e.what());
            return false;
        }
    }
    bool PDFWriter::add_polygon_annotation(const std::string &pdf_path,
                                           const std::vector<std::array<double, 2>> &vertices,
                                           const std::string &label,
                                           const std::array<uint8_t, 3> &color,
                                           double fill_opacity)
    {
        PolygonAnnotationData data;
        data.vertices = vertices;
        data.label = label;
        data.color = color;
        data.fill_opacity = fill_opacity;
        data.area_sf = 0.0;
        data.scale_factor1 = 1.0;
        data.scale_factor2 = 1.0;
        std::vector<PolygonAnnotationData> annotations = {data};
        return add_polygon_annotations_batch(pdf_path, annotations);
    }
    bool PDFWriter::add_polygon_annotations_batch(const std::string &pdf_path,
                                                  const std::vector<PolygonAnnotationData> &annotations)
    {
        if (annotations.empty())
        {
            return true;
        }
        try
        {
            QPDF pdf;
            pdf.processFile(pdf_path.c_str());
            QPDFPageDocumentHelper pages_helper(pdf);
            std::vector<QPDFPageObjectHelper> pages = pages_helper.getAllPages();
            if (pages.empty())
            {
                set_error("PDF has no pages");
                return false;
            }
            QPDFPageObjectHelper page = pages[0];
            QPDFObjectHandle page_dict = page.getObjectHandle();
            QPDFObjectHandle annots = get_or_create_annots(page_dict);
            for (const auto &annot_data : annotations)
            {
                BluebeamPolygon polygon;
                polygon.vertices = annot_data.vertices;
                polygon.holes = annot_data.holes;
                polygon.label = annot_data.label;
                polygon.stroke_color = annot_data.color;
                polygon.fill_color = annot_data.color;
                polygon.fill_opacity = annot_data.fill_opacity;
                std::string annot_dict_str = generate_bluebeam_polygon_dict(polygon);
                QPDFObjectHandle annot_obj = QPDFObjectHandle::parse(&pdf, annot_dict_str);
                QPDFObjectHandle annot = pdf.makeIndirectObject(annot_obj);
                annots.appendItem(annot);
            }
            QPDFWriter writer(pdf, pdf_path.c_str());
            writer.write();
            return true;
        }
        catch (const std::exception &e)
        {
            set_error(std::string("Failed to add annotations: ") + e.what());
            return false;
        }
    }
    static void add_polygons_to_page(QPDF &output,
                                     QPDFPageObjectHelper &page,
                                     const std::vector<PDFWriter::PolygonAnnotationData> &takeoffs)
    {
        if (takeoffs.empty())
        {
            return;
        }
        QPDFObjectHandle page_dict = page.getObjectHandle();
        QPDFObjectHandle annots = get_or_create_annots(page_dict);
        double sf1 = 1.0, sf2 = 1.0;
        bool has_measurements = false;
        for (const auto &takeoff : takeoffs)
        {
            if (takeoff.area_sf > 0.0)
            {
                sf1 = takeoff.scale_factor1;
                sf2 = takeoff.scale_factor2;
                has_measurements = true;
                break;
            }
        }
        QPDFObjectHandle helv_font_ref;
        QPDFObjectHandle annot_measure_ref;
        if (has_measurements)
        {
            std::string font_dict_str = generate_helvetica_font_dict();
            QPDFObjectHandle font_obj = QPDFObjectHandle::parse(&output, font_dict_str);
            helv_font_ref = output.makeIndirectObject(font_obj);
            replace_page_viewport_measure(
                output, page, make_page_measure_ref(output, sf1, sf2));
            std::string annot_measure_str = generate_annotation_measure_dict(sf1, sf2);
            QPDFObjectHandle annot_measure_obj = QPDFObjectHandle::parse(&output, annot_measure_str);
            annot_measure_ref = output.makeIndirectObject(annot_measure_obj);
        }
        for (const auto &takeoff : takeoffs)
        {
            BluebeamPolygon polygon;
            polygon.vertices = takeoff.vertices;
            polygon.holes = takeoff.holes;
            polygon.label = takeoff.label;
            polygon.stroke_color = takeoff.color;
            polygon.fill_color = takeoff.color;
            polygon.fill_opacity = takeoff.fill_opacity;
            polygon.area_sf = takeoff.area_sf;
            polygon.scale_factor1 = takeoff.scale_factor1;
            polygon.scale_factor2 = takeoff.scale_factor2;
            polygon.depth = takeoff.depth;
            std::string annot_dict_str = generate_bluebeam_polygon_dict(polygon);
            QPDFObjectHandle annot_obj = QPDFObjectHandle::parse(&output, annot_dict_str);
            if (has_measurements && takeoff.area_sf > 0.0)
            {
                annot_obj.replaceKey("/Measure", annot_measure_ref);
                annot_obj.replaceKey("/P", page_dict);
                std::string area_text = format_area_text(takeoff.area_sf);
                std::string ap_content = generate_appearance_stream_content(polygon, area_text);
                auto bb = compute_bbox_with_holes(polygon.vertices, polygon.holes);
                double rect_x1 = bb[0] - 5.5, rect_y1 = bb[1] - 5.5;
                double rect_x2 = bb[2] + 5.5, rect_y2 = bb[3] + 5.5;
                QPDFObjectHandle extra_res = QPDFObjectHandle::newDictionary();
                QPDFObjectHandle font_dict = QPDFObjectHandle::newDictionary();
                font_dict.replaceKey("/Helv", helv_font_ref);
                extra_res.replaceKey("/Font", font_dict);
                if (takeoff.fill_opacity > 0.0)
                {
                    QPDFObjectHandle gs0 = QPDFObjectHandle::newDictionary();
                    gs0.replaceKey("/Type", QPDFObjectHandle::newName("/ExtGState"));
                    gs0.replaceKey("/ca", QPDFObjectHandle::newReal(takeoff.fill_opacity));
                    QPDFObjectHandle ext_gstate = QPDFObjectHandle::newDictionary();
                    ext_gstate.replaceKey("/GS0", gs0);
                    extra_res.replaceKey("/ExtGState", ext_gstate);
                }
                attach_appearance_stream(output, annot_obj, ap_content,
                                         rect_x1, rect_y1, rect_x2, rect_y2, extra_res);
            }
            QPDFObjectHandle annot = output.makeIndirectObject(annot_obj);
            annots.appendItem(annot);
        }
    }
    static void add_arrows_to_page(QPDF &output,
                                   QPDFPageObjectHelper &page,
                                   const std::vector<PDFWriter::ArrowAnnotationData> &arrows)
    {
        if (arrows.empty())
        {
            return;
        }
        QPDFObjectHandle page_dict = page.getObjectHandle();
        QPDFObjectHandle annots = get_or_create_annots(page_dict);
        for (const auto &arrow_data : arrows)
        {
            BluebeamArrow arrow;
            arrow.x1 = arrow_data.x1;
            arrow.y1 = arrow_data.y1;
            arrow.x2 = arrow_data.x2;
            arrow.y2 = arrow_data.y2;
            arrow.color = arrow_data.color;
            arrow.width = arrow_data.width;
            std::string annot_dict_str = generate_bluebeam_arrow_dict(arrow);
            QPDFObjectHandle annot_obj = QPDFObjectHandle::parse(&output, annot_dict_str);
            annot_obj.replaceKey("/P", page_dict);
            std::string ap_content = generate_arrow_appearance_stream(arrow);
            std::array<double, 4> rect = compute_arrow_rect(arrow);
            attach_appearance_stream(output, annot_obj, ap_content,
                                     rect[0], rect[1], rect[2], rect[3]);
            QPDFObjectHandle annot = output.makeIndirectObject(annot_obj);
            annots.appendItem(annot);
        }
    }
    static void add_rects_to_page(QPDF &output,
                                  QPDFPageObjectHelper &page,
                                  const std::vector<PDFWriter::RectAnnotationData> &rects)
    {
        if (rects.empty())
        {
            return;
        }
        QPDFObjectHandle page_dict = page.getObjectHandle();
        QPDFObjectHandle annots = get_or_create_annots(page_dict);
        for (const auto &rect_data : rects)
        {
            BluebeamRect rect;
            rect.min_x = rect_data.min_x;
            rect.min_y = rect_data.min_y;
            rect.max_x = rect_data.max_x;
            rect.max_y = rect_data.max_y;
            rect.color = rect_data.color;
            rect.width = rect_data.width;
            std::string annot_dict_str = generate_bluebeam_rect_dict(rect);
            QPDFObjectHandle annot_obj = QPDFObjectHandle::parse(&output, annot_dict_str);
            annot_obj.replaceKey("/P", page_dict);
            std::string ap_content = generate_rect_appearance_stream(rect);
            attach_appearance_stream(output, annot_obj, ap_content,
                                     rect.min_x, rect.min_y, rect.max_x, rect.max_y);
            QPDFObjectHandle annot = output.makeIndirectObject(annot_obj);
            annots.appendItem(annot);
        }
    }
    static void add_lines_to_page(QPDF &output,
                                  QPDFPageObjectHelper &page,
                                  const std::vector<PDFWriter::LineAnnotationData> &lines)
    {
        if (lines.empty())
        {
            return;
        }
        QPDFObjectHandle page_dict = page.getObjectHandle();
        QPDFObjectHandle annots = get_or_create_annots(page_dict);
        for (const auto &line_data : lines)
        {
            BluebeamLine line;
            line.x1 = line_data.x1;
            line.y1 = line_data.y1;
            line.x2 = line_data.x2;
            line.y2 = line_data.y2;
            line.color = line_data.color;
            line.width = line_data.width;
            std::string annot_dict_str = generate_bluebeam_line_dict(line);
            QPDFObjectHandle annot_obj = QPDFObjectHandle::parse(&output, annot_dict_str);
            annot_obj.replaceKey("/P", page_dict);
            std::string ap_content = generate_line_appearance_stream(line);
            std::array<double, 4> rect = compute_line_rect(line);
            attach_appearance_stream(output, annot_obj, ap_content,
                                     rect[0], rect[1], rect[2], rect[3]);
            QPDFObjectHandle annot = output.makeIndirectObject(annot_obj);
            annots.appendItem(annot);
        }
    }
    static void add_dimensions_to_page(QPDF &output,
                                       QPDFPageObjectHelper &page,
                                       const std::vector<PDFWriter::DimensionAnnotationData> &dimensions)
    {
        if (dimensions.empty())
        {
            return;
        }
        QPDFObjectHandle page_dict = page.getObjectHandle();
        QPDFObjectHandle annots = get_or_create_annots(page_dict);
        std::string font_dict_str = generate_helvetica_font_dict();
        QPDFObjectHandle font_obj = QPDFObjectHandle::parse(&output, font_dict_str);
        QPDFObjectHandle helv_font_ref = output.makeIndirectObject(font_obj);
        for (const auto &dimension_data : dimensions)
        {
            if (has_valid_measure_scale(dimension_data.scale_factor1, dimension_data.scale_factor2))
            {
                ensure_page_viewport_measure(output, page,
                                             dimension_data.scale_factor1,
                                             dimension_data.scale_factor2);
                break;
            }
        }
        for (const auto &dimension_data : dimensions)
        {
            BluebeamDimension dimension;
            dimension.x1 = dimension_data.x1;
            dimension.y1 = dimension_data.y1;
            dimension.x2 = dimension_data.x2;
            dimension.y2 = dimension_data.y2;
            dimension.color = dimension_data.color;
            dimension.width = dimension_data.width;
            dimension.content = dimension_data.content;
            dimension.font_size = dimension_data.font_size;
            dimension.scale_factor1 = dimension_data.scale_factor1;
            dimension.scale_factor2 = dimension_data.scale_factor2;
            std::string annot_dict_str = generate_bluebeam_dimension_dict(dimension);
            QPDFObjectHandle annot_obj = QPDFObjectHandle::parse(&output, annot_dict_str);
            annot_obj.replaceKey("/P", page_dict);
            if (has_valid_measure_scale(dimension.scale_factor1, dimension.scale_factor2))
            {
                QPDFObjectHandle measure_ref = make_page_measure_ref(
                    output, dimension.scale_factor1, dimension.scale_factor2);
                annot_obj.replaceKey("/Measure", measure_ref);
            }
            std::string ap_content = generate_dimension_appearance_stream(dimension);
            QPDFObjectHandle extra_res = QPDFObjectHandle::newDictionary();
            QPDFObjectHandle font_res = QPDFObjectHandle::newDictionary();
            font_res.replaceKey("/Helv", helv_font_ref);
            extra_res.replaceKey("/Font", font_res);
            std::array<double, 4> rect = compute_dimension_rect(dimension);
            attach_appearance_stream(output, annot_obj, ap_content,
                                     rect[0], rect[1], rect[2], rect[3],
                                     extra_res);
            QPDFObjectHandle annot = output.makeIndirectObject(annot_obj);
            annots.appendItem(annot);
        }
    }
    static void add_ovals_to_page(QPDF &output,
                                  QPDFPageObjectHelper &page,
                                  const std::vector<PDFWriter::OvalAnnotationData> &ovals)
    {
        if (ovals.empty())
        {
            return;
        }
        QPDFObjectHandle page_dict = page.getObjectHandle();
        QPDFObjectHandle annots = get_or_create_annots(page_dict);
        for (const auto &oval_data : ovals)
        {
            BluebeamOval oval;
            oval.min_x = oval_data.min_x;
            oval.min_y = oval_data.min_y;
            oval.max_x = oval_data.max_x;
            oval.max_y = oval_data.max_y;
            oval.color = oval_data.color;
            oval.width = oval_data.width;
            std::string annot_dict_str = generate_bluebeam_oval_dict(oval);
            QPDFObjectHandle annot_obj = QPDFObjectHandle::parse(&output, annot_dict_str);
            annot_obj.replaceKey("/P", page_dict);
            std::string ap_content = generate_oval_appearance_stream(oval);
            attach_appearance_stream(output, annot_obj, ap_content,
                                     oval.min_x, oval.min_y, oval.max_x, oval.max_y);
            QPDFObjectHandle annot = output.makeIndirectObject(annot_obj);
            annots.appendItem(annot);
        }
    }
    static void add_polygons_annot_to_page(QPDF &output,
                                           QPDFPageObjectHelper &page,
                                           const std::vector<PDFWriter::PolygonAnnotationAnnotData> &polygons)
    {
        if (polygons.empty())
        {
            return;
        }
        QPDFObjectHandle page_dict = page.getObjectHandle();
        QPDFObjectHandle annots = get_or_create_annots(page_dict);
        for (const auto &poly_data : polygons)
        {
            BluebeamPolygonAnnot poly;
            poly.vertices = poly_data.vertices;
            poly.color = poly_data.color;
            poly.width = poly_data.width;
            poly.is_cloud = poly_data.is_cloud;
            std::string annot_dict_str = generate_bluebeam_polygon_annot_dict(poly);
            QPDFObjectHandle annot_obj = QPDFObjectHandle::parse(&output, annot_dict_str);
            annot_obj.replaceKey("/P", page_dict);
            std::string ap_content = generate_polygon_annot_appearance_stream(poly);
            auto rect = compute_polygon_annot_rect(poly);
            attach_appearance_stream(output, annot_obj, ap_content,
                                     rect[0], rect[1], rect[2], rect[3]);
            QPDFObjectHandle annot = output.makeIndirectObject(annot_obj);
            annots.appendItem(annot);
        }
    }
    static void add_inks_to_page(QPDF &output,
                                 QPDFPageObjectHelper &page,
                                 const std::vector<PDFWriter::InkAnnotationData> &inks)
    {
        if (inks.empty())
        {
            return;
        }
        QPDFObjectHandle page_dict = page.getObjectHandle();
        QPDFObjectHandle annots = get_or_create_annots(page_dict);
        for (const auto &ink_data : inks)
        {
            BluebeamInk ink;
            ink.strokes = ink_data.strokes;
            ink.color = ink_data.color;
            ink.width = ink_data.width;
            std::string annot_dict_str = generate_bluebeam_ink_dict(ink);
            QPDFObjectHandle annot_obj = QPDFObjectHandle::parse(&output, annot_dict_str);
            annot_obj.replaceKey("/P", page_dict);
            std::string ap_content = generate_ink_appearance_stream(ink);
            auto bb = compute_bbox_strokes(ink.strokes);
            attach_appearance_stream(output, annot_obj, ap_content,
                                     bb[0] - 7.0, bb[1] - 7.0, bb[2] + 7.0, bb[3] + 7.0);
            QPDFObjectHandle annot = output.makeIndirectObject(annot_obj);
            annots.appendItem(annot);
        }
    }
    static void add_texts_to_page(QPDF &output,
                                  QPDFPageObjectHelper &page,
                                  const std::vector<PDFWriter::TextAnnotationData> &texts)
    {
        if (texts.empty())
        {
            return;
        }
        QPDFObjectHandle page_dict = page.getObjectHandle();
        QPDFObjectHandle annots = get_or_create_annots(page_dict);
        std::string font_dict_str = generate_helvetica_font_dict();
        QPDFObjectHandle font_obj = QPDFObjectHandle::parse(&output, font_dict_str);
        QPDFObjectHandle helv_font_ref = output.makeIndirectObject(font_obj);
        for (const auto &text_data : texts)
        {
            BluebeamText text;
            text.min_x = text_data.min_x;
            text.min_y = text_data.min_y;
            text.max_x = text_data.max_x;
            text.max_y = text_data.max_y;
            text.content = text_data.content;
            text.font_size = text_data.font_size;
            text.color = text_data.color;
            text.text_align = text_data.text_align;
            std::string annot_dict_str = generate_bluebeam_text_dict(text);
            QPDFObjectHandle annot_obj = QPDFObjectHandle::parse(&output, annot_dict_str);
            annot_obj.replaceKey("/P", page_dict);
            std::string ap_content = generate_text_appearance_stream(text);
            QPDFObjectHandle extra_res = QPDFObjectHandle::newDictionary();
            QPDFObjectHandle font_res = QPDFObjectHandle::newDictionary();
            font_res.replaceKey("/Helv", helv_font_ref);
            extra_res.replaceKey("/Font", font_res);
            attach_appearance_stream(output, annot_obj, ap_content,
                                     text.min_x, text.min_y, text.max_x, text.max_y,
                                     extra_res);
            QPDFObjectHandle annot = output.makeIndirectObject(annot_obj);
            annots.appendItem(annot);
        }
    }
    static void add_highlights_to_page(QPDF &output,
                                       QPDFPageObjectHelper &page,
                                       const std::vector<PDFWriter::HighlightAnnotationData> &highlights)
    {
        if (highlights.empty())
        {
            return;
        }
        QPDFObjectHandle page_dict = page.getObjectHandle();
        QPDFObjectHandle annots = get_or_create_annots(page_dict);
        for (const auto &highlight_data : highlights)
        {
            std::vector<std::vector<std::array<double, 2>>> strokes;
            for (const auto &stroke : highlight_data.strokes)
            {
                if (stroke.size() >= 2)
                {
                    strokes.push_back(stroke);
                }
            }
            if (strokes.empty())
            {
                continue;
            }
            BluebeamHighlight highlight;
            highlight.strokes = strokes;
            highlight.color = highlight_data.color;
            highlight.width = std::max(1.0, highlight_data.width);
            highlight.opacity = highlight_data.opacity;
            highlight.content = highlight_data.content;
            std::string annot_dict_str = generate_bluebeam_highlight_dict(highlight);
            QPDFObjectHandle annot_obj = QPDFObjectHandle::parse(&output, annot_dict_str);
            annot_obj.replaceKey("/P", page_dict);
            QPDFObjectHandle gs = QPDFObjectHandle::newDictionary();
            gs.replaceKey("/Type", QPDFObjectHandle::newName("/ExtGState"));
            gs.replaceKey("/BM", QPDFObjectHandle::newName("/Multiply"));
            gs.replaceKey("/CA", QPDFObjectHandle::newReal(highlight.opacity));
            gs.replaceKey("/ca", QPDFObjectHandle::newReal(highlight.opacity));
            QPDFObjectHandle ext_gstate = QPDFObjectHandle::newDictionary();
            ext_gstate.replaceKey("/R0", gs);
            QPDFObjectHandle extra_res = QPDFObjectHandle::newDictionary();
            extra_res.replaceKey("/ExtGState", ext_gstate);
            std::string ap_content = generate_highlight_appearance_stream(highlight);
            auto rect = compute_highlight_rect(highlight);
            attach_appearance_stream(output, annot_obj, ap_content,
                                     rect[0], rect[1], rect[2], rect[3], extra_res);
            QPDFObjectHandle annot = output.makeIndirectObject(annot_obj);
            annots.appendItem(annot);
        }
    }
    bool PDFWriter::export_page_with_annotations(const std::string &source_pdf,
                                                 int page_index,
                                                 const std::string &output_pdf,
                                                 const std::vector<PolygonAnnotationData> &annotations)
    {
        try
        {
            QPDF source;
            source.processFile(source_pdf.c_str());
            QPDFPageDocumentHelper source_pages(source);
            std::vector<QPDFPageObjectHelper> pages = source_pages.getAllPages();
            if (page_index < 0 || page_index >= static_cast<int>(pages.size()))
            {
                set_error("Page index out of range: " + std::to_string(page_index));
                return false;
            }
            QPDF output;
            output.emptyPDF();
            QPDFPageDocumentHelper output_pages(output);
            QPDFPageObjectHelper selected_page = pages[page_index];
            output_pages.addPage(selected_page.getObjectHandle(), false);
            initialize_pdf_metadata(output);
            if (!annotations.empty())
            {
                std::vector<QPDFPageObjectHelper> output_page_list = output_pages.getAllPages();
                if (output_page_list.empty())
                {
                    set_error("No pages in output PDF");
                    return false;
                }
                add_polygons_to_page(output, output_page_list[0], annotations);
            }
            QPDFWriter writer(output, output_pdf.c_str());
            writer.setStaticID(true);
            writer.setMinimumPDFVersion("1.7");
            writer.write();
            return true;
        }
        catch (const std::exception &e)
        {
            set_error(std::string("Failed to export page with takeoffs: ") + e.what());
            return false;
        }
    }
    static QPDFObjectHandle create_blank_page_object(QPDF &qpdf, double width, double height, int rotation = 0)
    {
        QPDFObjectHandle page = QPDFObjectHandle::newDictionary();
        page.replaceKey("/Type", QPDFObjectHandle::newName("/Page"));
        QPDFObjectHandle media_box = QPDFObjectHandle::newArray();
        media_box.appendItem(QPDFObjectHandle::newInteger(0));
        media_box.appendItem(QPDFObjectHandle::newInteger(0));
        media_box.appendItem(QPDFObjectHandle::newReal(width));
        media_box.appendItem(QPDFObjectHandle::newReal(height));
        page.replaceKey("/MediaBox", media_box);
        if (rotation != 0)
            page.replaceKey("/Rotate", QPDFObjectHandle::newInteger(rotation));
        return qpdf.makeIndirectObject(page);
    }
    bool PDFWriter::merge_pages_with_annotations(const std::vector<PageExportData> &pages,
                                                 const std::string &output_pdf)
    {
        try
        {
            QPDF output;
            output.emptyPDF();
            initialize_pdf_metadata(output);
            QPDFPageDocumentHelper output_pages(output);
            for (const auto &page_data : pages)
            {
                if (page_data.is_blank || page_data.source_pdf.empty())
                {
                    double width = page_data.page_width > 0 ? page_data.page_width : 612.0;
                    double height = page_data.page_height > 0 ? page_data.page_height : 792.0;
                    QPDFObjectHandle blank_page = create_blank_page_object(output, width, height, page_data.rotation);
                    output_pages.addPage(blank_page, false);
                }
                else
                {
                    QPDF source;
                    source.processFile(page_data.source_pdf.c_str());
                    QPDFPageDocumentHelper source_pages(source);
                    std::vector<QPDFPageObjectHelper> source_page_list = source_pages.getAllPages();
                    if (page_data.page_index < 0 || page_data.page_index >= static_cast<int>(source_page_list.size()))
                    {
                        set_error("Page index out of range: " + std::to_string(page_data.page_index) +
                                  " in file: " + page_data.source_pdf);
                        return false;
                    }
                    QPDFPageObjectHelper selected_page = source_page_list[page_data.page_index];
                    output_pages.addPage(selected_page.getObjectHandle(), false);
                }
                QPDFPageObjectHelper last_page = output_pages.getAllPages().back();
                add_polygons_to_page(output, last_page, page_data.takeoffs);
                add_arrows_to_page(output, last_page, page_data.arrows);
                add_rects_to_page(output, last_page, page_data.rects);
                add_lines_to_page(output, last_page, page_data.lines);
                add_dimensions_to_page(output, last_page, page_data.dimensions);
                add_ovals_to_page(output, last_page, page_data.ovals);
                add_polygons_annot_to_page(output, last_page, page_data.polygons);
                add_inks_to_page(output, last_page, page_data.inks);
                add_texts_to_page(output, last_page, page_data.texts);
                add_highlights_to_page(output, last_page, page_data.highlights);
            }
            QPDFWriter writer(output, output_pdf.c_str());
            writer.setStaticID(true);
            writer.write();
            return true;
        }
        catch (const std::exception &e)
        {
            set_error(std::string("Failed to merge pages: ") + e.what());
            return false;
        }
    }
    std::vector<std::array<double, 4>> PDFWriter::get_page_sizes(const std::string &pdf_path)
    {
        std::vector<std::array<double, 4>> sizes;
        try
        {
            QPDF qpdf;
            qpdf.processFile(pdf_path.c_str());
            std::vector<QPDFPageObjectHelper> pages = QPDFPageDocumentHelper(qpdf).getAllPages();
            for (auto &page : pages)
            {
                QPDFObjectHandle media_box = page.getAttribute("/MediaBox", false);
                if (!media_box.isArray() || media_box.getArrayNItems() < 4)
                {
                    sizes.push_back({0.0, 0.0, 0.0, 0.0});
                    continue;
                }
                double llx = media_box.getArrayItem(0).getNumericValue();
                double lly = media_box.getArrayItem(1).getNumericValue();
                double urx = media_box.getArrayItem(2).getNumericValue();
                double ury = media_box.getArrayItem(3).getNumericValue();
                double width = urx - llx;
                double height = ury - lly;
                sizes.push_back({width, height, llx, lly});
            }
        }
        catch (const std::exception &e)
        {
            set_error(std::string("Failed to get page sizes: ") + e.what());
        }
        return sizes;
    }
}
