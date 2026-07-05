#include "bluebeam_annotation.hpp"
#include <sstream>
#include <iomanip>
#include <ctime>
#include <cmath>
#include <algorithm>
#include <cctype>
#include <random>
namespace ost_pdf_writer
{
    constexpr double CLOUD_BORDER_EFFECT_INTENSITY = 2.0;
    constexpr double CLOUD_SCALLOP_MIN_RADIUS = 15.0;
    constexpr double CLOUD_SCALLOP_MAX_RADIUS = 50.0;
    constexpr double CLOUD_SCALLOP_SIZE_SCALE = 0.25;

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
    static std::string escape_pdf_string(const std::string &s);
    static std::string escape_xml(const std::string &s);
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
    static std::string format_bluebeam_scale_text(double scale_factor)
    {
        std::ostringstream scale_value;
        scale_value << std::fixed << std::setprecision(8) << scale_factor;
        std::string scale_text = scale_value.str();
        while (scale_text.size() > 1 && scale_text.back() == '0')
        {
            scale_text.pop_back();
        }
        if (!scale_text.empty() && scale_text.back() == '.')
        {
            scale_text.pop_back();
        }
        std::replace(scale_text.begin(), scale_text.end(), '.', ',');
        return scale_text;
    }
    static std::string make_measure_dict(double scale_factor1,
                                         const std::string &d_entry,
                                         const std::string &v_entry)
    {
        double c_x = 1.0 / (scale_factor1 * 72.0);
        std::ostringstream oss;
        oss << "<<\n";
        oss << "/Type /Measure\n";
        oss << "/Subtype /RL\n";
        oss << "/R (" << format_bluebeam_scale_text(scale_factor1) << " in = 1 ft' in\")\n";
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

    static double point_distance(const std::array<double, 2> &a,
                                 const std::array<double, 2> &b)
    {
        return std::hypot(b[0] - a[0], b[1] - a[1]);
    }

    static std::array<double, 2> midpoint(const std::array<double, 2> &a,
                                          const std::array<double, 2> &b)
    {
        return {(a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5};
    }

    static std::array<double, 2> normalize(double x, double y)
    {
        double length = std::hypot(x, y);
        if (length <= 1e-12)
        {
            return {0.0, 0.0};
        }
        return {x / length, y / length};
    }

    static std::vector<std::array<double, 2>> normalize_cloud_vertices(
        const std::vector<std::array<double, 2>> &vertices)
    {
        std::vector<std::array<double, 2>> points = vertices;
        if (points.empty())
        {
            return points;
        }
        const auto &first = points.front();
        const auto &last = points.back();
        if (std::abs(first[0] - last[0]) > 1e-6 ||
            std::abs(first[1] - last[1]) > 1e-6)
        {
            points.push_back(first);
        }
        double area = 0.0;
        for (size_t i = 0; i < points.size(); ++i)
        {
            const auto &a = points[i];
            const auto &b = points[(i + 1) % points.size()];
            area += a[0] * b[1] - b[0] * a[1];
        }
        if (area < 0.0)
        {
            std::reverse(points.begin(), points.end());
        }
        return points;
    }

    struct PerimeterEdge
    {
        std::array<double, 2> start;
        std::array<double, 2> end;
        double length;
    };

    static std::vector<PerimeterEdge> polygon_perimeter_edges(
        const std::vector<std::array<double, 2>> &points)
    {
        std::vector<PerimeterEdge> edges;
        if (points.size() < 2)
        {
            return edges;
        }
        for (size_t i = 0; i < points.size(); ++i)
        {
            const auto &start = points[i];
            const auto &end = points[(i + 1) % points.size()];
            double length = point_distance(start, end);
            if (length > 1e-9)
            {
                edges.push_back({start, end, length});
            }
        }
        return edges;
    }

    static double calculate_cloud_scallop_radius(double average_edge_length)
    {
        double base_radius = std::max(
            CLOUD_SCALLOP_MIN_RADIUS,
            std::min(average_edge_length * CLOUD_BORDER_EFFECT_INTENSITY / 3.0,
                     CLOUD_SCALLOP_MAX_RADIUS));
        return base_radius * CLOUD_SCALLOP_SIZE_SCALE;
    }

    static std::vector<std::array<double, 2>> sample_along_perimeter(
        const std::vector<std::array<double, 2>> &points,
        int sample_count)
    {
        std::vector<std::array<double, 2>> samples;
        std::vector<PerimeterEdge> edges = polygon_perimeter_edges(points);
        if (edges.empty())
        {
            return samples;
        }
        double perimeter = 0.0;
        for (const auto &edge : edges)
        {
            perimeter += edge.length;
        }
        for (int k = 0; k < sample_count; ++k)
        {
            double target = (static_cast<double>(k) * perimeter) / sample_count;
            double accumulated = 0.0;
            for (const auto &edge : edges)
            {
                if (accumulated + edge.length >= target)
                {
                    double local = (target - accumulated) / edge.length;
                    samples.push_back({edge.start[0] + (edge.end[0] - edge.start[0]) * local,
                                       edge.start[1] + (edge.end[1] - edge.start[1]) * local});
                    break;
                }
                accumulated += edge.length;
            }
        }
        return samples;
    }

    static std::vector<std::array<double, 2>> compute_centers_from_samples(
        const std::vector<std::array<double, 2>> &samples,
        double radius)
    {
        std::vector<std::array<double, 2>> centers(samples.size(), {0.0, 0.0});
        for (size_t i = 0; i < samples.size(); ++i)
        {
            const auto &a = samples[i];
            const auto &b = samples[(i + 1) % samples.size()];
            auto mid = midpoint(a, b);
            double half_chord = point_distance(a, b) * 0.5;
            double inside = std::max(0.0, radius * radius - half_chord * half_chord);
            double offset = std::sqrt(inside);
            auto tangent = normalize(b[0] - a[0], b[1] - a[1]);
            double normal_x = -tangent[1];
            double normal_y = tangent[0];
            centers[(i + 1) % samples.size()] = {
                mid[0] + normal_x * offset,
                mid[1] + normal_y * offset};
        }
        return centers;
    }

    struct CloudCurveSegment
    {
        std::array<double, 2> start;
        std::array<double, 2> cp1;
        std::array<double, 2> cp2;
        std::array<double, 2> end;
    };

    static std::vector<CloudCurveSegment> cloud_arc_to_bezier(
        const std::array<double, 2> &center,
        double radius,
        double start_angle,
        double end_angle,
        const std::array<double, 2> &start)
    {
        constexpr double pi = 3.14159265358979323846;
        constexpr double kappa = 0.5522847498;
        while (end_angle < start_angle)
        {
            end_angle += 2.0 * pi;
        }
        double angle_span = end_angle - start_angle;
        int segment_count = std::max(1, static_cast<int>(std::ceil(std::abs(angle_span) / (pi / 2.0))));
        double segment_angle = angle_span / segment_count;
        std::vector<CloudCurveSegment> segments;
        std::array<double, 2> segment_start = start;
        for (int i = 0; i < segment_count; ++i)
        {
            double a1 = start_angle + i * segment_angle;
            double a2 = a1 + segment_angle;
            double cos_a1 = std::cos(a1);
            double sin_a1 = std::sin(a1);
            double cos_a2 = std::cos(a2);
            double sin_a2 = std::sin(a2);
            std::array<double, 2> end = {
                center[0] + radius * cos_a2,
                center[1] + radius * sin_a2};
            double d = std::abs(segment_angle - pi / 2.0) > 1e-6
                           ? radius * kappa * std::tan(segment_angle / 4.0) / std::tan(pi / 8.0)
                           : radius * kappa;
            std::array<double, 2> cp1 = {
                center[0] + radius * cos_a1 - d * sin_a1,
                center[1] + radius * sin_a1 + d * cos_a1};
            std::array<double, 2> cp2 = {
                end[0] + d * sin_a2,
                end[1] - d * cos_a2};
            segments.push_back({segment_start, cp1, cp2, end});
            segment_start = end;
        }
        return segments;
    }

    static std::vector<CloudCurveSegment> build_cloud_curve_segments(
        const std::vector<std::array<double, 2>> &vertices)
    {
        constexpr double pi = 3.14159265358979323846;
        std::vector<CloudCurveSegment> segments;
        if (vertices.size() < 2)
        {
            return segments;
        }
        std::vector<std::array<double, 2>> points = normalize_cloud_vertices(vertices);
        std::vector<PerimeterEdge> edges = polygon_perimeter_edges(points);
        if (edges.empty())
        {
            return segments;
        }
        double average_edge_length = 0.0;
        double perimeter = 0.0;
        for (const auto &edge : edges)
        {
            average_edge_length += edge.length;
            perimeter += edge.length;
        }
        average_edge_length /= static_cast<double>(edges.size());
        double radius = calculate_cloud_scallop_radius(average_edge_length);
        int sample_count = std::max(6, static_cast<int>(std::ceil(perimeter / (3.25 * radius))));
        std::vector<std::array<double, 2>> samples = sample_along_perimeter(points, sample_count);
        if (samples.size() < 2)
        {
            return segments;
        }
        std::vector<std::array<double, 2>> centers = compute_centers_from_samples(samples, radius);
        for (size_t k = 0; k < samples.size(); ++k)
        {
            const auto &start = samples[k];
            const auto &end = samples[(k + 1) % samples.size()];
            const auto &center = centers[(k + 1) % samples.size()];
            double r = point_distance(center, start);
            double start_angle = std::atan2(start[1] - center[1], start[0] - center[0]);
            double end_angle = std::atan2(end[1] - center[1], end[0] - center[0]);
            while (end_angle < start_angle)
            {
                end_angle += 2.0 * pi;
            }
            if (end_angle - start_angle > pi)
            {
                end_angle -= 2.0 * pi;
            }
            std::vector<CloudCurveSegment> arc_segments =
                cloud_arc_to_bezier(center, r, start_angle, end_angle, start);
            segments.insert(segments.end(), arc_segments.begin(), arc_segments.end());
        }
        return segments;
    }

    static void emit_cloud_appearance_path(std::ostringstream &oss,
                                           const std::vector<CloudCurveSegment> &segments)
    {
        if (segments.empty())
        {
            return;
        }
        oss << segments.front().start[0] << " " << segments.front().start[1] << " m ";
        for (const auto &segment : segments)
        {
            oss << segment.cp1[0] << " " << segment.cp1[1] << " "
                << segment.cp2[0] << " " << segment.cp2[1] << " "
                << segment.end[0] << " " << segment.end[1] << " c ";
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
    static void add_bbox_point(std::array<double, 4> &bb, double x, double y)
    {
        if (x < bb[0])
            bb[0] = x;
        if (x > bb[2])
            bb[2] = x;
        if (y < bb[1])
            bb[1] = y;
        if (y > bb[3])
            bb[3] = y;
    }
    struct ArrowGeometry
    {
        double left_x;
        double left_y;
        double right_x;
        double right_y;
    };
    static ArrowGeometry compute_arrow_geometry(const BluebeamArrow &arrow)
    {
        double head_length = arrow.width * 8.0;
        double head_width = arrow.width * 6.0;
        double angle = std::atan2(arrow.y2 - arrow.y1, arrow.x2 - arrow.x1);
        double back_x = arrow.x2 - head_length * std::cos(angle);
        double back_y = arrow.y2 - head_length * std::sin(angle);
        return {
            back_x - head_width * std::sin(angle),
            back_y + head_width * std::cos(angle),
            back_x + head_width * std::sin(angle),
            back_y - head_width * std::cos(angle)};
    }
    std::array<double, 4> compute_arrow_rect(const BluebeamArrow &arrow)
    {
        ArrowGeometry head = compute_arrow_geometry(arrow);
        std::array<double, 4> bb{
            std::min(arrow.x1, arrow.x2),
            std::min(arrow.y1, arrow.y2),
            std::max(arrow.x1, arrow.x2),
            std::max(arrow.y1, arrow.y2)};
        add_bbox_point(bb, head.left_x, head.left_y);
        add_bbox_point(bb, head.right_x, head.right_y);
        double padding = std::max(2.0, arrow.width);
        bb[0] -= padding;
        bb[1] -= padding;
        bb[2] += padding;
        bb[3] += padding;
        return bb;
    }
    std::string generate_bluebeam_arrow_dict(const BluebeamArrow &arrow)
    {
        std::ostringstream oss;
        std::array<double, 4> rect = compute_arrow_rect(arrow);
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
        oss << "/LE [ /None /ClosedArrow ]\n";
        oss << "/M (" << pdf_date << ")\n";
        oss << "/NM (" << nm << ")\n";
        oss << "/PitchRun 12\n";
        oss << "/Rect [ " << rect[0] << " " << rect[1] << " " << rect[2] << " " << rect[3] << " ]\n";
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
        ArrowGeometry head = compute_arrow_geometry(arrow);
        std::ostringstream oss;
        oss << stroke_r << " " << stroke_g << " " << stroke_b << " RG ";
        oss << stroke_r << " " << stroke_g << " " << stroke_b << " rg ";
        oss << arrow.width << " w ";
        oss << arrow.x1 << " " << arrow.y1 << " m ";
        oss << arrow.x2 << " " << arrow.y2 << " l S ";
        oss << head.left_x << " " << head.left_y << " m ";
        oss << arrow.x2 << " " << arrow.y2 << " l ";
        oss << head.right_x << " " << head.right_y << " l b ";
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
    std::array<double, 4> compute_line_rect(const BluebeamLine &line)
    {
        double padding = 5.0 + line.width;
        return {
            std::min(line.x1, line.x2) - padding,
            std::min(line.y1, line.y2) - padding,
            std::max(line.x1, line.x2) + padding,
            std::max(line.y1, line.y2) + padding};
    }
    std::string generate_bluebeam_line_dict(const BluebeamLine &line)
    {
        std::ostringstream oss;
        std::array<double, 4> rect = compute_line_rect(line);
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
        oss << "/PitchRun 12\n";
        oss << "/Rect [ " << rect[0] << " " << rect[1] << " " << rect[2] << " " << rect[3] << " ]\n";
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
    static double dimension_text_width(const BluebeamDimension &dimension)
    {
        double font_size = std::max(1.0, dimension.font_size);
        return std::max(font_size * 2.0,
                        static_cast<double>(dimension.content.size()) * font_size * 0.55);
    }
    struct DimensionTextLayout
    {
        double center_x;
        double center_y;
        double ux;
        double uy;
        double nx;
        double ny;
        double text_width;
        double text_half_height;
    };
    static DimensionTextLayout calculate_dimension_text_layout(
        const BluebeamDimension &dimension,
        double dx,
        double dy)
    {
        double font_size = std::max(1.0, dimension.font_size);
        double angle = std::atan2(dy, dx);
        constexpr double pi = 3.14159265358979323846;
        if (angle > pi / 2.0 || angle < -pi / 2.0)
        {
            angle += pi;
        }
        double ux = std::cos(angle);
        double uy = std::sin(angle);
        double nx = -uy;
        double ny = ux;
        double offset = std::max(4.0, font_size * 0.35);
        return {
            (dimension.x1 + dimension.x2) / 2.0 + nx * offset,
            (dimension.y1 + dimension.y2) / 2.0 + ny * offset,
            ux,
            uy,
            nx,
            ny,
            dimension_text_width(dimension),
            font_size * 0.65};
    }
    std::array<double, 4> compute_dimension_rect(const BluebeamDimension &dimension)
    {
        std::array<double, 4> bb{
            std::min(dimension.x1, dimension.x2),
            std::min(dimension.y1, dimension.y2),
            std::max(dimension.x1, dimension.x2),
            std::max(dimension.y1, dimension.y2)};
        double dx = dimension.x2 - dimension.x1;
        double dy = dimension.y2 - dimension.y1;
        double length = std::hypot(dx, dy);
        double font_size = std::max(1.0, dimension.font_size);
        double text_width = dimension_text_width(dimension);
        if (length > 1e-9)
        {
            double ux = dx / length;
            double uy = dy / length;
            double nx = -uy;
            double ny = ux;
            double tick_half = std::max(5.0, font_size * 0.4);
            add_bbox_point(bb, dimension.x1 + nx * tick_half, dimension.y1 + ny * tick_half);
            add_bbox_point(bb, dimension.x1 - nx * tick_half, dimension.y1 - ny * tick_half);
            add_bbox_point(bb, dimension.x2 + nx * tick_half, dimension.y2 + ny * tick_half);
            add_bbox_point(bb, dimension.x2 - nx * tick_half, dimension.y2 - ny * tick_half);

            DimensionTextLayout text = calculate_dimension_text_layout(dimension, dx, dy);
            double along_x = text.ux * text.text_width / 2.0;
            double along_y = text.uy * text.text_width / 2.0;
            double normal_x = text.nx * text.text_half_height;
            double normal_y = text.ny * text.text_half_height;
            add_bbox_point(bb, text.center_x + along_x + normal_x, text.center_y + along_y + normal_y);
            add_bbox_point(bb, text.center_x + along_x - normal_x, text.center_y + along_y - normal_y);
            add_bbox_point(bb, text.center_x - along_x + normal_x, text.center_y - along_y + normal_y);
            add_bbox_point(bb, text.center_x - along_x - normal_x, text.center_y - along_y - normal_y);
        }
        else
        {
            double text_padding = std::max(12.0, text_width / 2.0);
            bb[0] -= text_padding;
            bb[2] += text_padding;
            bb[1] -= font_size;
            bb[3] += font_size;
        }
        double padding = std::max(6.0, dimension.width + 3.0);
        bb[0] -= padding;
        bb[1] -= padding;
        bb[2] += padding;
        bb[3] += padding;
        return bb;
    }
    std::string generate_bluebeam_dimension_dict(const BluebeamDimension &dimension)
    {
        std::ostringstream oss;
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(dimension.color);
        std::string hex_color = rgb_to_hex(dimension.color);
        std::string pdf_date = dimension.created_date.empty() ? generate_pdf_date() : dimension.created_date;
        std::string nm = generate_nm();
        std::string escaped_content = escape_pdf_string(dimension.content);
        std::string xml_content = escape_xml(dimension.content);
        std::array<double, 4> rect = compute_dimension_rect(dimension);
        double font_size = std::max(1.0, dimension.font_size);
        double line_height = font_size * 1.15;
        std::ostringstream lh_str;
        lh_str << std::fixed << std::setprecision(5) << line_height;
        oss << "<<\n";
        oss << "/BS << /S /S /Type /Border /W " << dimension.width << " >>\n";
        oss << "/C [ " << stroke_r << " " << stroke_g << " " << stroke_b << " ]\n";
        oss << "/Cap true\n";
        oss << "/Contents (" << escaped_content << ")\n";
        oss << "/CreationDate (" << pdf_date << ")\n";
        oss << "/DA (" << stroke_r << " " << stroke_g << " " << stroke_b << " rg /Helv " << font_size << " Tf)\n";
        oss << "/DS (font: Helvetica " << font_size << "pt; text-align:center; line-height:"
            << lh_str.str() << "pt; color:" << hex_color << ")\n";
        oss << "/DepthUnit [ << /Type /NumberFormat /U (mm) /C 0.3527778 /D 100 /FD true /SS () >> ]\n";
        oss << "/F 4\n";
        oss << "/IC [ " << stroke_r << " " << stroke_g << " " << stroke_b << " ]\n";
        oss << "/IT /LineDimension\n";
        oss << "/L [ " << dimension.x1 << " " << dimension.y1 << " " << dimension.x2 << " " << dimension.y2 << " ]\n";
        oss << "/Label ()\n";
        oss << "/LE [ /ClosedArrow /ClosedArrow ]\n";
        oss << "/LL 10\n";
        oss << "/LLE 2\n";
        oss << "/M (" << pdf_date << ")\n";
        oss << "/MeasurementTypes 130\n";
        oss << "/NM (" << nm << ")\n";
        oss << "/PitchRun 12\n";
        oss << "/RC (<?xml version=\"1.0\"?>"
            << "<body xmlns:xfa=\"http://www.xfa.org/schema/xfa-data/1.0/\" "
            << "xfa:contentType=\"text/html\" "
            << "xfa:APIVersion=\"BluebeamPDFRevu:2018\" "
            << "xfa:spec=\"2.2.0\" "
            << "style=\"font:Helvetica " << font_size << "pt; text-align:center; line-height:"
            << lh_str.str() << "pt; color:" << hex_color << "\" "
            << "xmlns=\"http://www.w3.org/1999/xhtml\">"
            << "<p>" << xml_content << "</p>"
            << "</body>)\n";
        oss << "/Rect [ " << rect[0] << " " << rect[1] << " " << rect[2] << " " << rect[3] << " ]\n";
        oss << "/SlopeType 1\n";
        oss << "/Subj (Length Measurement)\n";
        oss << "/Subtype /Line\n";
        oss << "/T (" << escape_pdf_string(dimension.author) << ")\n";
        oss << "/Type /Annot\n";
        oss << ">>";
        return oss.str();
    }
    std::string generate_dimension_appearance_stream(const BluebeamDimension &dimension)
    {
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(dimension.color);
        double dx = dimension.x2 - dimension.x1;
        double dy = dimension.y2 - dimension.y1;
        double length = std::hypot(dx, dy);
        if (length <= 1e-9)
        {
            return "";
        }
        double font_size = std::max(1.0, dimension.font_size);
        double ux = dx / length;
        double uy = dy / length;
        double nx = -uy;
        double ny = ux;
        double tick_half = std::max(5.0, font_size * 0.4);
        std::ostringstream oss;
        oss << stroke_r << " " << stroke_g << " " << stroke_b << " RG ";
        oss << stroke_r << " " << stroke_g << " " << stroke_b << " rg ";
        oss << dimension.width << " w ";
        oss << dimension.x1 << " " << dimension.y1 << " m ";
        oss << dimension.x2 << " " << dimension.y2 << " l S ";
        oss << dimension.x1 + nx * tick_half << " " << dimension.y1 + ny * tick_half << " m ";
        oss << dimension.x1 - nx * tick_half << " " << dimension.y1 - ny * tick_half << " l S ";
        oss << dimension.x2 + nx * tick_half << " " << dimension.y2 + ny * tick_half << " m ";
        oss << dimension.x2 - nx * tick_half << " " << dimension.y2 - ny * tick_half << " l S ";
        if (!dimension.content.empty())
        {
            DimensionTextLayout text = calculate_dimension_text_layout(dimension, dx, dy);
            double text_x = text.center_x - text.ux * text.text_width / 2.0 - text.nx * font_size * 0.35;
            double text_y = text.center_y - text.uy * text.text_width / 2.0 - text.ny * font_size * 0.35;
            oss << "q BT "
                << stroke_r << " " << stroke_g << " " << stroke_b << " rg "
                << "/Helv " << font_size << " Tf "
                << text.ux << " " << text.uy << " " << -text.uy << " " << text.ux << " "
                << text_x << " " << text_y << " Tm "
                << "(" << escape_pdf_string(dimension.content) << ") Tj "
                << "ET Q ";
        }
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
        auto rect = compute_polygon_annot_rect(poly);
        auto [stroke_r, stroke_g, stroke_b] = color_to_rgb(poly.color);
        std::string pdf_date = poly.created_date.empty() ? generate_pdf_date() : poly.created_date;
        std::string nm = generate_nm();
        std::string subject = poly.is_cloud ? "Cloud" : "Polygon";
        oss << "<<\n";
        if (poly.is_cloud)
        {
            oss << "/BE << /S /C /I 2 >>\n";
        }
        oss << "/BS << /S /S /Type /Border /W " << poly.width << " >>\n";
        oss << "/C [ " << stroke_r << " " << stroke_g << " " << stroke_b << " ]\n";
        oss << "/CreationDate (" << pdf_date << ")\n";
        oss << "/F 4\n";
        if (poly.is_cloud)
        {
            oss << "/IT /PolygonCloud\n";
        }
        oss << "/M (" << pdf_date << ")\n";
        oss << "/NM (" << nm << ")\n";
        oss << "/Rect [ " << rect[0] << " " << rect[1] << " " << rect[2] << " " << rect[3] << " ]\n";
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
        if (poly.is_cloud)
        {
            std::vector<CloudCurveSegment> cloud_segments = build_cloud_curve_segments(poly.vertices);
            if (!cloud_segments.empty())
            {
                oss << "1 j 1 J ";
                emit_cloud_appearance_path(oss, cloud_segments);
            }
            else
            {
                emit_subpath(oss, poly.vertices);
            }
        }
        else
        {
            emit_subpath(oss, poly.vertices);
        }
        oss << "S ";
        return oss.str();
    }
    std::array<double, 4> compute_polygon_annot_rect(const BluebeamPolygonAnnot &poly)
    {
        auto bb = compute_bbox(poly.vertices);
        if (poly.is_cloud)
        {
            std::vector<CloudCurveSegment> cloud_segments = build_cloud_curve_segments(poly.vertices);
            for (const auto &segment : cloud_segments)
            {
                add_bbox_point(bb, segment.start[0], segment.start[1]);
                add_bbox_point(bb, segment.cp1[0], segment.cp1[1]);
                add_bbox_point(bb, segment.cp2[0], segment.cp2[1]);
                add_bbox_point(bb, segment.end[0], segment.end[1]);
            }
        }
        double padding = poly.is_cloud ? std::max(5.0, poly.width / 2.0 + 2.0) : 5.0;
        return {bb[0] - padding, bb[1] - padding, bb[2] + padding, bb[3] + padding};
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
    static int text_align_to_pdf_q(const std::string &align)
    {
        if (align == "center")
        {
            return 1;
        }
        if (align == "right")
        {
            return 2;
        }
        return 0;
    }

    static double estimate_text_width(const std::string &text, double font_size)
    {
        double width = 0.0;
        for (unsigned char c : text)
        {
            width += (std::isspace(c) ? 0.30 : 0.55) * font_size;
        }
        return width;
    }

    static std::vector<std::string> split_long_word(
        const std::string &word,
        double max_width,
        double font_size)
    {
        std::vector<std::string> chunks;
        std::string current;
        for (char c : word)
        {
            std::string candidate = current + c;
            if (!current.empty() && estimate_text_width(candidate, font_size) > max_width)
            {
                chunks.push_back(current);
                current = std::string(1, c);
            }
            else
            {
                current = candidate;
            }
        }
        if (!current.empty())
        {
            chunks.push_back(current);
        }
        return chunks;
    }

    static void append_wrapped_word(
        std::vector<std::string> &lines,
        std::string &current_line,
        const std::string &word,
        double max_width,
        double font_size)
    {
        if (word.empty())
        {
            return;
        }
        std::string candidate = current_line.empty() ? word : current_line + " " + word;
        if (estimate_text_width(candidate, font_size) <= max_width)
        {
            current_line = candidate;
            return;
        }
        if (!current_line.empty())
        {
            lines.push_back(current_line);
            current_line.clear();
        }
        if (estimate_text_width(word, font_size) <= max_width)
        {
            current_line = word;
            return;
        }
        std::vector<std::string> chunks = split_long_word(word, max_width, font_size);
        for (size_t i = 0; i < chunks.size(); ++i)
        {
            if (i + 1 == chunks.size())
            {
                current_line = chunks[i];
            }
            else
            {
                lines.push_back(chunks[i]);
            }
        }
    }

    static std::vector<std::string> wrap_text_lines(
        const std::string &content,
        double max_width,
        double font_size)
    {
        std::vector<std::string> lines;
        std::string current_line;
        std::string current_word;
        for (char c : content)
        {
            if (c == '\r')
            {
                continue;
            }
            if (c == '\n')
            {
                append_wrapped_word(lines, current_line, current_word, max_width, font_size);
                current_word.clear();
                lines.push_back(current_line);
                current_line.clear();
                continue;
            }
            if (std::isspace(static_cast<unsigned char>(c)))
            {
                append_wrapped_word(lines, current_line, current_word, max_width, font_size);
                current_word.clear();
                continue;
            }
            current_word += c;
        }
        append_wrapped_word(lines, current_line, current_word, max_width, font_size);
        if (!current_line.empty() || lines.empty())
        {
            lines.push_back(current_line);
        }
        return lines;
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
        oss << "/Q " << text_align_to_pdf_q(align) << "\n";
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
        double margin = 3.0;
        double box_width = std::max(1.0, text.max_x - text.min_x);
        double box_height = std::max(1.0, text.max_y - text.min_y);
        double max_text_width = std::max(1.0, box_width - margin * 2.0);
        double line_height = std::max(1.0, text.font_size * 1.15);
        std::vector<std::string> lines = wrap_text_lines(text.content, max_text_width, text.font_size);
        double y_text = text.max_y - margin - text.font_size;
        std::ostringstream oss;
        oss << "q 1 0 0 1 0 0 cm "
            << text.min_x << " " << text.min_y << " " << box_width << " " << box_height << " re W n "
            << "1 1 1 rg "
            << r << " " << g << " " << b << " RG 0 w "
            << "BT "
            << r << " " << g << " " << b << " rg "
            << "/Helv " << text.font_size << " Tf ";
        for (const std::string &line : lines)
        {
            if (y_text < text.min_y + margin)
            {
                break;
            }
            double line_width = estimate_text_width(line, text.font_size);
            double x_text = text.min_x + margin;
            if (text.text_align == "center")
            {
                x_text = text.min_x + (box_width - line_width) / 2.0;
            }
            else if (text.text_align == "right")
            {
                x_text = text.max_x - line_width - margin;
            }
            oss << "1 0 0 1 " << x_text << " " << y_text << " Tm "
                << "(" << escape_pdf_string(line) << ") Tj ";
            y_text -= line_height;
        }
        oss << "ET Q";
        return oss.str();
    }
    std::array<double, 4> compute_highlight_rect(const BluebeamHighlight &highlight)
    {
        auto bb = compute_bbox_strokes(highlight.strokes);
        double padding = highlight.width / 2.0 + 2.0;
        return {bb[0] - padding, bb[1] - padding, bb[2] + padding, bb[3] + padding};
    }
    std::string generate_bluebeam_highlight_dict(const BluebeamHighlight &highlight)
    {
        std::ostringstream oss;
        auto rect = compute_highlight_rect(highlight);
        auto [r, g, b] = color_to_rgb(highlight.color);
        std::string pdf_date = highlight.created_date.empty() ? generate_pdf_date() : highlight.created_date;
        std::string nm = generate_nm();
        oss << "<<\n";
        oss << "/BM /Multiply\n";
        oss << "/BS << /S /S /Type /Border /W " << highlight.width << " >>\n";
        oss << "/C [ " << r << " " << g << " " << b << " ]\n";
        if (!highlight.content.empty())
        {
            oss << "/Contents (" << escape_pdf_string(highlight.content) << ")\n";
        }
        oss << "/CreationDate (" << pdf_date << ")\n";
        oss << "/F 4\n";
        oss << "/InkList [ ";
        for (const auto &stroke : highlight.strokes)
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
        oss << "/Rect [ " << rect[0] << " " << rect[1] << " " << rect[2] << " " << rect[3] << " ]\n";
        oss << "/Subj (Highlight)\n";
        oss << "/Subtype /Ink\n";
        oss << "/T (" << escape_pdf_string(highlight.author) << ")\n";
        oss << "/Type /Annot\n";
        oss << ">>";
        return oss.str();
    }
    std::string generate_highlight_appearance_stream(const BluebeamHighlight &highlight)
    {
        auto [r, g, b] = color_to_rgb(highlight.color);
        std::ostringstream oss;
        oss << "/R0 gs ";
        oss << r << " " << g << " " << b << " RG ";
        oss << highlight.width << " w 1 j 1 J ";
        for (const auto &stroke : highlight.strokes)
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
}
