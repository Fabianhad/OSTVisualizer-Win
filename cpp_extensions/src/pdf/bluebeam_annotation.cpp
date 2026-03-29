#include "bluebeam_annotation.hpp"
#include <sstream>
#include <iomanip>
#include <ctime>
#include <cmath>
#include <algorithm>
#include <numeric>
#include <random>
#include <limits>
namespace ost_pdf_writer
{
    static std::string decimal_to_fraction(double decimal, int max_denominator = 64)
    {
        if (decimal <= 0)
            return "0";
        double intpart;
        double frac = std::modf(decimal, &intpart);
        if (frac < 1e-10)
        {
            return std::to_string(static_cast<int>(intpart));
        }
        double best_error = std::numeric_limits<double>::max();
        int best_num = 0, best_den = 1;
        for (int den = 1; den <= max_denominator; ++den)
        {
            int num = static_cast<int>(std::round(decimal * den));
            if (num <= 0)
                continue;
            double error = std::abs(static_cast<double>(num) / den - decimal);
            if (error < best_error)
            {
                best_error = error;
                best_num = num;
                best_den = den;
            }
        }
        int gcd = std::gcd(best_num, best_den);
        best_num /= gcd;
        best_den /= gcd;
        std::ostringstream oss;
        if (intpart > 0)
        {
            oss << static_cast<int>(intpart) << " ";
        }
        oss << best_num << "/" << best_den;
        return oss.str();
    }
    std::string generate_nm()
    {
        static std::mt19937 rng(std::random_device{}());
        static std::uniform_int_distribution<int> dist(0, 25);
        std::string nm;
        nm.reserve(16);
        for (int i = 0; i < 16; ++i)
            nm += static_cast<char>('A' + dist(rng));
        return nm;
    }
    static std::string generate_pdf_date()
    {
        std::time_t now = std::time(nullptr);
        std::tm tm{};
#ifdef _WIN32
        localtime_s(&tm, &now);
#else
        localtime_r(&now, &tm);
#endif
        char buf[64];
        std::strftime(buf, sizeof(buf), "D:%Y%m%d%H%M%S", &tm);
        long tz_offset = 0;
#ifdef _WIN32
        _get_timezone(&tz_offset);
        int tz_hours = -static_cast<int>(tz_offset / 3600);
        int dst = 0;
        _get_daylight(&dst);
        if (dst && tm.tm_isdst > 0)
            tz_hours += 1;
#else
        tz_offset = tm.tm_gmtoff;
        int tz_hours = static_cast<int>(tz_offset / 3600);
#endif
        int tz_mins = std::abs(static_cast<int>((tz_offset % 3600) / 60));
        std::ostringstream oss;
        oss << buf;
        if (tz_hours >= 0)
            oss << "+" << std::setw(2) << std::setfill('0') << tz_hours;
        else
            oss << "-" << std::setw(2) << std::setfill('0') << std::abs(tz_hours);
        oss << "'" << std::setw(2) << std::setfill('0') << tz_mins << "'";
        return oss.str();
    }
    std::string format_area_text(double area_sf)
    {
        std::ostringstream oss;
        oss << std::fixed << std::setprecision(2) << area_sf;
        std::string num_str = oss.str();
        auto dot_pos = num_str.find('.');
        std::string int_part = num_str.substr(0, dot_pos);
        std::string dec_part = num_str.substr(dot_pos + 1);
        std::string formatted;
        int count = 0;
        for (int i = static_cast<int>(int_part.size()) - 1; i >= 0; --i)
        {
            if (count > 0 && count % 3 == 0 && int_part[i] != '-')
                formatted = "," + formatted;
            formatted = int_part[i] + formatted;
            ++count;
        }
        return formatted + "." + dec_part + " sf";
    }
    static std::string rgb_to_hex(const std::array<uint8_t, 3> &color)
    {
        std::ostringstream oss;
        oss << "#" << std::hex << std::uppercase << std::setfill('0')
            << std::setw(2) << static_cast<int>(color[0])
            << std::setw(2) << static_cast<int>(color[1])
            << std::setw(2) << static_cast<int>(color[2]);
        return oss.str();
    }
    static std::array<double, 3> color_to_rgb(const std::array<uint8_t, 3> &c)
    {
        return {c[0] / 255.0, c[1] / 255.0, c[2] / 255.0};
    }
    static std::array<double, 4> compute_bbox(
        const std::vector<std::array<double, 2>> &verts)
    {
        double min_x = verts[0][0], min_y = verts[0][1];
        double max_x = verts[0][0], max_y = verts[0][1];
        for (const auto &v : verts)
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
        const std::vector<std::array<double, 2>> &verts,
        const std::vector<std::vector<std::array<double, 2>>> &holes)
    {
        auto bb = compute_bbox(verts);
        for (const auto &hole : holes)
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
        return bb;
    }
    static std::array<double, 4> compute_bbox_strokes(
        const std::vector<std::vector<std::array<double, 2>>> &strokes)
    {
        double min_x = strokes[0][0][0], min_y = strokes[0][0][1];
        double max_x = strokes[0][0][0], max_y = strokes[0][0][1];
        for (const auto &stroke : strokes)
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
        return {min_x, min_y, max_x, max_y};
    }
    static std::string make_measure_dict(double scale_factor1,
                                         const std::string &d_entry,
                                         const std::string &v_entry)
    {
        double c_x = 1.0 / (scale_factor1 * 72.0);
        std::string scale_fraction = decimal_to_fraction(scale_factor1);
        std::ostringstream oss;
        oss << "<<\n";
        oss << "/Type /Measure\n";
        oss << "/Subtype /RL\n";
        oss << "/R (" << scale_fraction << "\" = 1'0\")\n";
        oss << "/X [<< /Type /NumberFormat /U (') /C " << c_x << " /F /F /D 4 /FD true /SS () >>]\n";
        oss << d_entry;
        oss << "/A [<< /Type /NumberFormat /U (sf) /C 1 /D 100 /FD true /SS () >>]\n";
        oss << "/T [<< /Type /NumberFormat /U (\\260) /C 1 /D 100 /FD true /PS () /SS () >>]\n";
        oss << v_entry;
        oss << "/TargetUnitConversion 0.001157407\n";
        oss << ">>";
        return oss.str();
    }
    std::string generate_bluebeam_polygon_dict(const BluebeamPolygon &polygon)
    {
        std::ostringstream oss;
        auto bb = compute_bbox(polygon.vertices);
        double rect_x1 = bb[0] - 5.5, rect_y1 = bb[1] - 5.5;
        double rect_x2 = bb[2] + 5.5, rect_y2 = bb[3] + 5.5;
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(polygon.stroke_color);
        std::string hex_color = rgb_to_hex(polygon.stroke_color);
        std::string area_text = format_area_text(polygon.area_sf);
        std::string pdf_date = generate_pdf_date();
        std::string nm = generate_nm();
        oss << "<<\n";
        oss << "/AlignOnSegment true\n";
        oss << "/Cap true\n";
        oss << "/C [ " << stroke_r << " " << stroke_g << " " << stroke_b << " ]\n";
        oss << "/Contents (" << area_text << ")\n";
        oss << "/CreationDate (" << pdf_date << ")\n";
        if (!polygon.holes.empty())
        {
            oss << "/Cutouts [ ";
            for (const auto &hole : polygon.holes)
            {
                oss << "[ ";
                for (const auto &vertex : hole)
                {
                    oss << vertex[0] << " " << vertex[1] << " ";
                }
                oss << "] ";
            }
            oss << "]\n";
        }
        if (polygon.depth > 0.0)
        {
            oss << "/Depth " << polygon.depth << "\n";
        }
        oss << "/DepthUnit [ << /Type /NumberFormat /U (') /C 0.001157407 /D 100 /FD true /SS () >> ]\n";
        oss << "/DS (font: Helvetica 12pt; text-align:center; line-height:13.8pt; color:" << hex_color << ")\n";
        oss << "/F 4\n";
        oss << "/FillOpacity " << polygon.fill_opacity << "\n";
        oss << "/IC [ " << stroke_r << " " << stroke_g << " " << stroke_b << " ]\n";
        oss << "/IT /PolygonDimension\n";
        oss << "/Label ()\n";
        oss << "/M (" << pdf_date << ")\n";
        oss << "/MeasurementTypes 129\n";
        oss << "/NM (" << nm << ")\n";
        oss << "/PitchRun 12\n";
        oss << "/RC (<?xml version=\"1.0\"?>"
            << "<body xmlns:xfa=\"http://www.xfa.org/schema/xfa-data/1.0/\" "
            << "xfa:contentType=\"text/html\" "
            << "xfa:APIVersion=\"BluebeamPDFRevu:2018\" "
            << "xfa:spec=\"2.2.0\" "
            << "style=\"font:Helvetica 12pt; text-align:center; line-height:13.8pt; color:" << hex_color << "\" "
            << "xmlns=\"http://www.w3.org/1999/xhtml\">"
            << "<p>" << area_text << "</p>"
            << "</body>)\n";
        oss << "/Rect [ " << rect_x1 << " " << rect_y1 << " " << rect_x2 << " " << rect_y2 << " ]\n";
        oss << "/SlopeType 1\n";
        oss << "/Subj (Area Measurement)\n";
        oss << "/Subtype /Polygon\n";
        oss << "/T (" << polygon.author << ")\n";
        oss << "/Type /Annot\n";
        oss << "/Vertices [ ";
        for (const auto &vertex : polygon.vertices)
        {
            oss << vertex[0] << " " << vertex[1] << " ";
        }
        oss << "]\n";
        oss << ">>";
        return oss.str();
    }
    std::string generate_page_measure_dict(double scale_factor1, double scale_factor2)
    {
        (void)scale_factor2;
        return make_measure_dict(
            scale_factor1,
            "/D [<< /Type /NumberFormat /U (') /C 1 /F /F /D 4 /FD true /PS () /SS (-) >>"
            " << /Type /NumberFormat /U (\") /C 12 /F /F /D 4 /FD true /PS () /SS () >>]\n",
            "/V [<< /Type /NumberFormat /U (cu ft) /C 1 /D 100 /FD true /SS () >>]\n");
    }
    std::string generate_annotation_measure_dict(double scale_factor1, double scale_factor2)
    {
        (void)scale_factor2;
        return make_measure_dict(
            scale_factor1,
            "/D [<< /Type /NumberFormat /U (mm) /C 304.8 /D 100 /SS () >>]\n",
            "/V [<< /Type /NumberFormat /U (cu yd) /C 0.03703704 /D 100 /FD true /SS () >>]\n");
    }
    std::string generate_helvetica_font_dict()
    {
        std::ostringstream oss;
        oss << "<<\n";
        oss << "/Name /Helv\n";
        oss << "/Type /Font\n";
        oss << "/BaseFont /Helvetica\n";
        oss << "/Subtype /Type1\n";
        oss << "/Encoding <<\n";
        oss << "  /Type /Encoding\n";
        oss << "  /Differences [\n";
        oss << "    24 /breve /caron /circumflex /dotaccent /hungarumlaut /ogonek /ring /tilde\n";
        oss << "    39 /quotesingle\n";
        oss << "    96 /grave\n";
        oss << "    127 /.notdef /bullet /dagger /daggerdbl /ellipsis /emdash /endash /florin /fraction\n";
        oss << "    /guilsinglleft /guilsinglright /minus /perthousand /quotedblbase /quotedblleft\n";
        oss << "    /quotedblright /quoteleft /quoteright /quotesinglbase /trademark /fi /fl /Lslash\n";
        oss << "    /OE /Scaron /Ydieresis /Zcaron /dotlessi /lslash /oe /scaron /zcaron /.notdef /Euro\n";
        oss << "    164 /currency\n";
        oss << "    166 /brokenbar\n";
        oss << "    168 /dieresis /copyright /ordfeminine\n";
        oss << "    172 /logicalnot /.notdef /registered /macron /degree /plusminus /twosuperior\n";
        oss << "    /threesuperior /acute /mu\n";
        oss << "    183 /periodcentered /cedilla /onesuperior /ordmasculine\n";
        oss << "    188 /onequarter /onehalf /threequarters\n";
        oss << "    192 /Agrave /Aacute /Acircumflex /Atilde /Adieresis /Aring /AE /Ccedilla /Egrave\n";
        oss << "    /Eacute /Ecircumflex /Edieresis /Igrave /Iacute /Icircumflex /Idieresis /Eth /Ntilde\n";
        oss << "    /Ograve /Oacute /Ocircumflex /Otilde /Odieresis /multiply /Oslash /Ugrave /Uacute\n";
        oss << "    /Ucircumflex /Udieresis /Yacute /Thorn /germandbls /agrave /aacute /acircumflex\n";
        oss << "    /atilde /adieresis /aring /ae /ccedilla /egrave /eacute /ecircumflex /edieresis\n";
        oss << "    /igrave /iacute /icircumflex /idieresis /eth /ntilde /ograve /oacute /ocircumflex\n";
        oss << "    /otilde /odieresis /divide /oslash /ugrave /uacute /ucircumflex /udieresis /yacute\n";
        oss << "    /thorn /ydieresis\n";
        oss << "  ]\n";
        oss << ">>\n";
        oss << ">>";
        return oss.str();
    }
    static void emit_subpath(std::ostringstream &oss,
                             const std::vector<std::array<double, 2>> &verts)
    {
        bool first = true;
        for (const auto &v : verts)
        {
            if (first)
            {
                oss << v[0] << " " << v[1] << " m ";
                first = false;
            }
            else
            {
                oss << v[0] << " " << v[1] << " l ";
            }
        }
        oss << "h ";
    }
    std::string generate_appearance_stream_content(const BluebeamPolygon &polygon,
                                                   const std::string &area_text)
    {
        auto bb = compute_bbox_with_holes(polygon.vertices, polygon.holes);
        auto [fill_r, fill_g, fill_b] = color_to_rgb(polygon.fill_color);
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(polygon.stroke_color);
        bool has_holes = !polygon.holes.empty();
        std::ostringstream oss;
        if (polygon.fill_opacity > 0.0)
        {
            oss << "q /GS0 gs ";
            oss << fill_r << " " << fill_g << " " << fill_b << " rg ";
            oss << stroke_r << " " << stroke_g << " " << stroke_b << " RG ";
            oss << polygon.stroke_width << " w ";
            emit_subpath(oss, polygon.vertices);
            for (const auto &hole : polygon.holes)
            {
                emit_subpath(oss, hole);
            }
            if (has_holes)
                oss << "B* Q ";
            else
                oss << "b Q ";
        }
        else
        {
            oss << stroke_r << " " << stroke_g << " " << stroke_b << " RG "
                << polygon.stroke_width << " w ";
            emit_subpath(oss, polygon.vertices);
            for (const auto &hole : polygon.holes)
            {
                emit_subpath(oss, hole);
            }
            oss << "S ";
        }
        double center_x = (bb[0] + bb[2]) / 2.0;
        double center_y = (bb[1] + bb[3]) / 2.0;
        double text_width = area_text.size() * 6.0;
        double text_x = center_x - text_width / 2.0;
        double text_y = center_y - 6.0;
        oss << "q 1 0 0 1 0 0 cm BT "
            << stroke_r << " " << stroke_g << " " << stroke_b << " rg "
            << "/Helv 12 Tf "
            << "1 0 0 1 " << text_x << " " << text_y << " Tm "
            << "(" << area_text << ") Tj ET Q ";
        return oss.str();
    }
    std::string generate_bluebeam_arrow_dict(const BluebeamArrow &arrow)
    {
        std::ostringstream oss;
        double padding_x = 22.0 + arrow.width * 1.5;
        double padding_y = 6.0 + arrow.width * 0.75;
        double rect_x1 = std::min(arrow.x1, arrow.x2) - padding_x;
        double rect_y1 = std::min(arrow.y1, arrow.y2) - padding_y;
        double rect_x2 = std::max(arrow.x1, arrow.x2) + padding_x;
        double rect_y2 = std::max(arrow.y1, arrow.y2) + padding_y;
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(arrow.color);
        std::string pdf_date = arrow.created_date.empty() ? generate_pdf_date() : arrow.created_date;
        std::string nm = generate_nm();
        oss << "<<\n";
        oss << "/BS << /S /S /Type /Border /W " << arrow.width << " >>\n";
        oss << "/C [ " << stroke_r << " " << stroke_g << " " << stroke_b << " ]\n";
        oss << "/CreationDate (" << pdf_date << ")\n";
        oss << "/F 4\n";
        oss << "/IC [ " << stroke_r << " " << stroke_g << " " << stroke_b << " ]\n";
        oss << "/IT /LineArrow\n";
        oss << "/L [ " << arrow.x1 << " " << arrow.y1 << " " << arrow.x2 << " " << arrow.y2 << " ]\n";
        oss << "/LE [ /None /OpenArrow ]\n";
        oss << "/M (" << pdf_date << ")\n";
        oss << "/NM (" << nm << ")\n";
        oss << "/P 5 0 R\n";
        oss << "/PitchRun 12\n";
        oss << "/Rect [ " << rect_x1 << " " << rect_y1 << " " << rect_x2 << " " << rect_y2 << " ]\n";
        oss << "/SlopeType 0\n";
        oss << "/Subj (Arrow)\n";
        oss << "/Subtype /Line\n";
        oss << "/T (" << arrow.author << ")\n";
        oss << "/Type /Annot\n";
        oss << ">>";
        return oss.str();
    }
    std::string generate_arrow_appearance_stream(const BluebeamArrow &arrow)
    {
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(arrow.color);
        double arrow_head_length = arrow.width * 8.0;
        double arrow_head_width = arrow.width * 6.0;
        double dx = arrow.x2 - arrow.x1;
        double dy = arrow.y2 - arrow.y1;
        double angle = std::atan2(dy, dx);
        double arrow_tip_x = arrow.x2;
        double arrow_tip_y = arrow.y2;
        double arrow_back_x = arrow_tip_x - arrow_head_length * std::cos(angle);
        double arrow_back_y = arrow_tip_y - arrow_head_length * std::sin(angle);
        double left_x = arrow_back_x - arrow_head_width * std::sin(angle);
        double left_y = arrow_back_y + arrow_head_width * std::cos(angle);
        double right_x = arrow_back_x + arrow_head_width * std::sin(angle);
        double right_y = arrow_back_y - arrow_head_width * std::cos(angle);
        std::ostringstream oss;
        oss << stroke_r << " " << stroke_g << " " << stroke_b << " RG ";
        oss << stroke_r << " " << stroke_g << " " << stroke_b << " rg ";
        oss << arrow.width << " w ";
        oss << arrow.x1 << " " << arrow.y1 << " m ";
        oss << arrow.x2 << " " << arrow.y2 << " l S ";
        oss << left_x << " " << left_y << " m ";
        oss << arrow_tip_x << " " << arrow_tip_y << " l ";
        oss << right_x << " " << right_y << " l b ";
        return oss.str();
    }
    std::string generate_bluebeam_rect_dict(const BluebeamRect &rect)
    {
        std::ostringstream oss;
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(rect.color);
        std::string pdf_date = rect.created_date.empty() ? generate_pdf_date() : rect.created_date;
        std::string nm = generate_nm();
        oss << "<<\n";
        oss << "/BS << /S /S /Type /Border /W " << rect.width << " >>\n";
        oss << "/C [ " << stroke_r << " " << stroke_g << " " << stroke_b << " ]\n";
        oss << "/CreationDate (" << pdf_date << ")\n";
        oss << "/F 4\n";
        oss << "/M (" << pdf_date << ")\n";
        oss << "/NM (" << nm << ")\n";
        oss << "/P 5 0 R\n";
        oss << "/RD [ 2 2 2 2 ]\n";
        oss << "/Rect [ " << rect.min_x << " " << rect.min_y << " " << rect.max_x << " " << rect.max_y << " ]\n";
        oss << "/Subj (Rectangle)\n";
        oss << "/Subtype /Square\n";
        oss << "/T (" << rect.author << ")\n";
        oss << "/Type /Annot\n";
        oss << ">>";
        return oss.str();
    }
    std::string generate_rect_appearance_stream(const BluebeamRect &rect)
    {
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(rect.color);
        double width = rect.max_x - rect.min_x;
        double height = rect.max_y - rect.min_y;
        double inset = 2.0;
        double x = rect.min_x + inset;
        double y = rect.min_y + inset;
        double w = width - 2 * inset;
        double h = height - 2 * inset;
        std::ostringstream oss;
        oss << stroke_r << " " << stroke_g << " " << stroke_b << " RG ";
        oss << rect.width << " w ";
        oss << x << " " << y << " " << w << " " << h << " re S ";
        return oss.str();
    }
    std::string generate_bluebeam_line_dict(const BluebeamLine &line)
    {
        std::ostringstream oss;
        double padding = 5.0 + line.width;
        double rect_x1 = std::min(line.x1, line.x2) - padding;
        double rect_y1 = std::min(line.y1, line.y2) - padding;
        double rect_x2 = std::max(line.x1, line.x2) + padding;
        double rect_y2 = std::max(line.y1, line.y2) + padding;
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(line.color);
        std::string pdf_date = line.created_date.empty() ? generate_pdf_date() : line.created_date;
        std::string nm = generate_nm();
        oss << "<<\n";
        oss << "/BS << /S /S /Type /Border /W " << line.width << " >>\n";
        oss << "/C [ " << stroke_r << " " << stroke_g << " " << stroke_b << " ]\n";
        oss << "/CreationDate (" << pdf_date << ")\n";
        oss << "/F 4\n";
        oss << "/L [ " << line.x1 << " " << line.y1 << " " << line.x2 << " " << line.y2 << " ]\n";
        oss << "/LE [ /None /None ]\n";
        oss << "/M (" << pdf_date << ")\n";
        oss << "/NM (" << nm << ")\n";
        oss << "/P 5 0 R\n";
        oss << "/PitchRun 12\n";
        oss << "/Rect [ " << rect_x1 << " " << rect_y1 << " " << rect_x2 << " " << rect_y2 << " ]\n";
        oss << "/SlopeType 0\n";
        oss << "/Subj (Line)\n";
        oss << "/Subtype /Line\n";
        oss << "/T (" << line.author << ")\n";
        oss << "/Type /Annot\n";
        oss << ">>";
        return oss.str();
    }
    std::string generate_line_appearance_stream(const BluebeamLine &line)
    {
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(line.color);
        std::ostringstream oss;
        oss << stroke_r << " " << stroke_g << " " << stroke_b << " RG ";
        oss << line.width << " w ";
        oss << line.x1 << " " << line.y1 << " m ";
        oss << line.x2 << " " << line.y2 << " l S ";
        return oss.str();
    }
    std::string generate_bluebeam_oval_dict(const BluebeamOval &oval)
    {
        std::ostringstream oss;
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(oval.color);
        std::string pdf_date = oval.created_date.empty() ? generate_pdf_date() : oval.created_date;
        std::string nm = generate_nm();
        oss << "<<\n";
        oss << "/C [ " << stroke_r << " " << stroke_g << " " << stroke_b << " ]\n";
        oss << "/CreationDate (" << pdf_date << ")\n";
        oss << "/F 4\n";
        oss << "/M (" << pdf_date << ")\n";
        oss << "/NM (" << nm << ")\n";
        oss << "/P 5 0 R\n";
        oss << "/RD [ 0.5 0.5 0.5 0.5 ]\n";
        oss << "/Rect [ " << oval.min_x << " " << oval.min_y << " " << oval.max_x << " " << oval.max_y << " ]\n";
        oss << "/Subj (Ellipse)\n";
        oss << "/Subtype /Circle\n";
        oss << "/T (" << oval.author << ")\n";
        oss << "/Type /Annot\n";
        oss << ">>";
        return oss.str();
    }
    std::string generate_oval_appearance_stream(const BluebeamOval &oval)
    {
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(oval.color);
        double width = oval.max_x - oval.min_x;
        double height = oval.max_y - oval.min_y;
        double cx = (oval.min_x + oval.max_x) / 2.0;
        double cy = (oval.min_y + oval.max_y) / 2.0;
        double rx = width / 2.0;
        double ry = height / 2.0;
        double kappa = 0.5522847498;
        double ox = rx * kappa;
        double oy = ry * kappa;
        std::ostringstream oss;
        oss << stroke_r << " " << stroke_g << " " << stroke_b << " RG ";
        oss << oval.width << " w ";
        oss << (cx + rx) << " " << cy << " m ";
        oss << (cx + rx) << " " << (cy + oy) << " ";
        oss << (cx + ox) << " " << (cy + ry) << " ";
        oss << cx << " " << (cy + ry) << " c ";
        oss << (cx - ox) << " " << (cy + ry) << " ";
        oss << (cx - rx) << " " << (cy + oy) << " ";
        oss << (cx - rx) << " " << cy << " c ";
        oss << (cx - rx) << " " << (cy - oy) << " ";
        oss << (cx - ox) << " " << (cy - ry) << " ";
        oss << cx << " " << (cy - ry) << " c ";
        oss << (cx + ox) << " " << (cy - ry) << " ";
        oss << (cx + rx) << " " << (cy - oy) << " ";
        oss << (cx + rx) << " " << cy << " c S ";
        return oss.str();
    }
    std::string generate_bluebeam_polygon_annot_dict(const BluebeamPolygonAnnot &poly)
    {
        std::ostringstream oss;
        auto bb = compute_bbox(poly.vertices);
        double rect_x1 = bb[0] - 5.0, rect_y1 = bb[1] - 5.0;
        double rect_x2 = bb[2] + 5.0, rect_y2 = bb[3] + 5.0;
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(poly.color);
        std::string pdf_date = poly.created_date.empty() ? generate_pdf_date() : poly.created_date;
        std::string nm = generate_nm();
        std::string subject = poly.is_cloud ? "Cloud" : "Polygon";
        oss << "<<\n";
        if (poly.is_cloud)
        {
            oss << "/BE << /S /C /I 2 >>\n";
        }
        oss << "/C [ " << stroke_r << " " << stroke_g << " " << stroke_b << " ]\n";
        oss << "/CreationDate (" << pdf_date << ")\n";
        oss << "/F 4\n";
        if (poly.is_cloud)
        {
            oss << "/IT /PolygonCloud\n";
        }
        oss << "/M (" << pdf_date << ")\n";
        oss << "/NM (" << nm << ")\n";
        oss << "/P 5 0 R\n";
        oss << "/Rect [ " << rect_x1 << " " << rect_y1 << " " << rect_x2 << " " << rect_y2 << " ]\n";
        oss << "/Subj (" << subject << ")\n";
        oss << "/Subtype /Polygon\n";
        oss << "/T (" << poly.author << ")\n";
        oss << "/Type /Annot\n";
        oss << "/Vertices [ ";
        for (const auto &vertex : poly.vertices)
        {
            oss << vertex[0] << " " << vertex[1] << " ";
        }
        oss << "]\n";
        oss << ">>";
        return oss.str();
    }
    std::string generate_polygon_annot_appearance_stream(const BluebeamPolygonAnnot &poly)
    {
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(poly.color);
        std::ostringstream oss;
        oss << stroke_r << " " << stroke_g << " " << stroke_b << " RG ";
        oss << poly.width << " w ";
        emit_subpath(oss, poly.vertices);
        oss << "S ";
        return oss.str();
    }
    std::string generate_bluebeam_ink_dict(const BluebeamInk &ink)
    {
        std::ostringstream oss;
        auto bb = compute_bbox_strokes(ink.strokes);
        double rect_x1 = bb[0] - 7.0, rect_y1 = bb[1] - 7.0;
        double rect_x2 = bb[2] + 7.0, rect_y2 = bb[3] + 7.0;
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(ink.color);
        std::string pdf_date = ink.created_date.empty() ? generate_pdf_date() : ink.created_date;
        std::string nm = generate_nm();
        oss << "<<\n";
        oss << "/BS << /S /S /Type /Border /W " << ink.width << " >>\n";
        oss << "/C [ " << stroke_r << " " << stroke_g << " " << stroke_b << " ]\n";
        oss << "/CreationDate (" << pdf_date << ")\n";
        oss << "/F 4\n";
        oss << "/InkList [ ";
        for (const auto &stroke : ink.strokes)
        {
            oss << "[ ";
            for (const auto &point : stroke)
            {
                oss << point[0] << " " << point[1] << " ";
            }
            oss << "] ";
        }
        oss << "]\n";
        oss << "/M (" << pdf_date << ")\n";
        oss << "/NM (" << nm << ")\n";
        oss << "/P 5 0 R\n";
        oss << "/Rect [ " << rect_x1 << " " << rect_y1 << " " << rect_x2 << " " << rect_y2 << " ]\n";
        oss << "/Subj (Pen)\n";
        oss << "/Subtype /Ink\n";
        oss << "/T (" << ink.author << ")\n";
        oss << "/Type /Annot\n";
        oss << ">>";
        return oss.str();
    }
    std::string generate_ink_appearance_stream(const BluebeamInk &ink)
    {
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(ink.color);
        std::ostringstream oss;
        oss << stroke_r << " " << stroke_g << " " << stroke_b << " RG ";
        oss << ink.width << " w ";
        for (const auto &stroke : ink.strokes)
        {
            if (stroke.empty())
                continue;
            bool first = true;
            for (const auto &point : stroke)
            {
                if (first)
                {
                    oss << point[0] << " " << point[1] << " m ";
                    first = false;
                }
                else
                {
                    oss << point[0] << " " << point[1] << " l ";
                }
            }
            oss << "S ";
        }
        return oss.str();
    }
    static std::string escape_pdf_string(const std::string &s)
    {
        std::string result;
        result.reserve(s.size());
        for (char c : s)
        {
            if (c == '(' || c == ')' || c == '\\')
                result += '\\';
            result += c;
        }
        return result;
    }
    static std::string escape_xml(const std::string &s)
    {
        std::string result;
        result.reserve(s.size());
        for (char c : s)
        {
            if (c == '&')
                result += "&amp;";
            else if (c == '<')
                result += "&lt;";
            else if (c == '>')
                result += "&gt;";
            else if (c == '"')
                result += "&quot;";
            else
                result += c;
        }
        return result;
    }
    std::string generate_bluebeam_text_dict(const BluebeamText &text)
    {
        auto [r, g, b] = color_to_rgb(text.color);
        std::string hex_color = rgb_to_hex(text.color);
        std::string pdf_date = text.created_date.empty() ? generate_pdf_date() : text.created_date;
        std::string nm = generate_nm();
        std::string escaped_content = escape_pdf_string(text.content);
        std::string xml_content = escape_xml(text.content);
        double line_height = text.font_size * 1.15;
        std::ostringstream lh_str;
        lh_str << std::fixed << std::setprecision(5) << line_height;
        std::string line_height_str = lh_str.str();
        std::string align = text.text_align.empty() ? "left" : text.text_align;
        std::ostringstream oss;
        oss << "<<\n";
        oss << "/BS << /W 0 /S /S /Type /Border >>\n";
        oss << "/C []\n";
        oss << "/Contents (" << escaped_content << ")\n";
        oss << "/CreationDate (" << pdf_date << ")\n";
        oss << "/DA (" << r << " " << g << " " << b << " rg /Helv " << text.font_size << " Tf)\n";
        oss << "/DS (font: Helvetica " << text.font_size << "pt; text-align:" << align
            << "; margin:3pt; line-height:" << line_height_str << "pt; color:" << hex_color << ")\n";
        oss << "/F 4\n";
        oss << "/M (" << pdf_date << ")\n";
        oss << "/NM (" << nm << ")\n";
        oss << "/RC (<?xml version=\"1.0\"?>"
            << "<body xmlns:xfa=\"http://www.xfa.org/schema/xfa-data/1.0/\" "
            << "xfa:contentType=\"text/html\" "
            << "xfa:APIVersion=\"BluebeamPDFRevu:2018\" "
            << "xfa:spec=\"2.2.0\" "
            << "style=\"font:Helvetica " << text.font_size << "pt; text-align:" << align
            << "; margin:3pt; line-height:" << line_height_str << "pt; color:" << hex_color << "\" "
            << "xmlns=\"http://www.w3.org/1999/xhtml\">"
            << "<p>" << xml_content << "</p>"
            << "</body>)\n";
        oss << "/Rect [ " << text.min_x << " " << text.min_y << " " << text.max_x << " " << text.max_y << " ]\n";
        oss << "/Subj (Text Box)\n";
        oss << "/Subtype /FreeText\n";
        oss << "/T (" << escape_pdf_string(text.author) << ")\n";
        oss << "/Type /Annot\n";
        oss << ">>";
        return oss.str();
    }
    std::string generate_text_appearance_stream(const BluebeamText &text)
    {
        auto [r, g, b] = color_to_rgb(text.color);
        std::string escaped_content = escape_pdf_string(text.content);
        double x_text = text.min_x + 3.0;
        double y_text = text.min_y + 3.0 + text.font_size * 0.25;
        std::ostringstream oss;
        oss << "q 1 0 0 1 0 0 cm 1 1 1 rg "
            << r << " " << g << " " << b << " RG 0 w "
            << "BT "
            << r << " " << g << " " << b << " rg "
            << "/Helv " << text.font_size << " Tf "
            << "1 0 0 1 " << x_text << " " << y_text << " Tm "
            << "(" << escaped_content << ") Tj "
            << "ET Q";
        return oss.str();
    }
}
