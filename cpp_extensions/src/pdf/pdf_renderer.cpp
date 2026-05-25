#include "pdf_renderer.hpp"
#include <fpdfview.h>
#include <fpdf_doc.h>
#include <fpdf_edit.h>
#include <fpdf_text.h>
#include <algorithm>
#include <mutex>
#include <atomic>
#include <cstring>
namespace ost_pdf
{
#define DOC() (static_cast<FPDF_DOCUMENT>(doc_))
    static std::once_flag g_init_flag;
    static std::atomic<bool> g_initialized{false};
    void initialize_pdfium()
    {
        std::call_once(g_init_flag, []()
                       {
        FPDF_InitLibrary();
        g_initialized = true; });
    }
    void shutdown_pdfium()
    {
        if (g_initialized.exchange(false))
        {
            FPDF_DestroyLibrary();
        }
    }
    namespace
    {
        void append_utf8(std::string &text, unsigned int codepoint)
        {
            if (codepoint <= 0x7F)
            {
                text.push_back(static_cast<char>(codepoint));
            }
            else if (codepoint <= 0x7FF)
            {
                text.push_back(static_cast<char>(0xC0 | (codepoint >> 6)));
                text.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
            }
            else if (codepoint <= 0xFFFF)
            {
                text.push_back(static_cast<char>(0xE0 | (codepoint >> 12)));
                text.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
                text.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
            }
            else if (codepoint <= 0x10FFFF)
            {
                text.push_back(static_cast<char>(0xF0 | (codepoint >> 18)));
                text.push_back(static_cast<char>(0x80 | ((codepoint >> 12) & 0x3F)));
                text.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
                text.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
            }
        }

        bool is_text_separator(unsigned int codepoint)
        {
            return codepoint == 0 ||
                   codepoint == '\t' ||
                   codepoint == '\n' ||
                   codepoint == '\r' ||
                   codepoint == ' ';
        }

        struct PDFiumCleanup
        {
            ~PDFiumCleanup() { shutdown_pdfium(); }
        };
        static PDFiumCleanup g_cleanup;
    }
    PDFRenderer::PDFRenderer()
    {
        initialize_pdfium();
    }
    PDFRenderer::~PDFRenderer()
    {
        close();
    }
    PDFRenderer::PDFRenderer(PDFRenderer &&other) noexcept
        : doc_(other.doc_), last_error_(std::move(other.last_error_))
    {
        other.doc_ = nullptr;
    }
    PDFRenderer &PDFRenderer::operator=(PDFRenderer &&other) noexcept
    {
        if (this != &other)
        {
            close();
            doc_ = other.doc_;
            last_error_ = std::move(other.last_error_);
            other.doc_ = nullptr;
        }
        return *this;
    }
    bool PDFRenderer::open(const std::string &path)
    {
        close();
        last_error_.clear();
        doc_ = FPDF_LoadDocument(path.c_str(), nullptr);
        if (doc_)
        {
            return true;
        }
        return false;
    }
    void PDFRenderer::close()
    {
        if (doc_)
        {
            FPDF_CloseDocument(DOC());
            doc_ = nullptr;
        }
    }
    bool PDFRenderer::is_open() const
    {
        return doc_ != nullptr;
    }
    std::string PDFRenderer::get_last_error() const
    {
        return last_error_;
    }
    int PDFRenderer::page_count() const
    {
        return doc_ ? FPDF_GetPageCount(DOC()) : 0;
    }
    std::pair<double, double> PDFRenderer::page_size(int page_index) const
    {
        if (!doc_ || page_index < 0 || page_index >= page_count())
        {
            return {0.0, 0.0};
        }
        FPDF_PAGE page = FPDF_LoadPage(DOC(), page_index);
        if (!page)
        {
            return {0.0, 0.0};
        }
        double width = FPDF_GetPageWidth(page);
        double height = FPDF_GetPageHeight(page);
        FPDF_ClosePage(page);
        return {width, height};
    }
    std::string PDFRenderer::page_label(int page_index) const
    {
        if (!doc_ || page_index < 0 || page_index >= page_count())
        {
            return {};
        }
        unsigned long len = FPDF_GetPageLabel(DOC(), page_index, nullptr, 0);
        if (len <= 2)
        {
            return {};
        }
        std::vector<char> buf(len);
        FPDF_GetPageLabel(DOC(), page_index, buf.data(), len);
        std::string result;
        for (unsigned long i = 0; i + 1 < len; i += 2)
        {
            unsigned char lo = static_cast<unsigned char>(buf[i]);
            unsigned char hi = static_cast<unsigned char>(buf[i + 1]);
            if (lo == 0 && hi == 0)
                break;
            if (hi == 0 && lo >= 0x20 && lo < 0x7F)
            {
                result.push_back(static_cast<char>(lo));
            }
            else
            {
                result.push_back('?');
            }
        }
        return result;
    }
    std::optional<PageInfo> PDFRenderer::page_info(int page_index) const
    {
        if (!doc_ || page_index < 0 || page_index >= page_count())
        {
            return std::nullopt;
        }
        double media_w = 0.0, media_h = 0.0;
        if (!FPDF_GetPageSizeByIndex(DOC(), page_index, &media_w, &media_h))
        {
            return std::nullopt;
        }
        int intrinsic_rotation = 0;
        double effective_w = media_w;
        double effective_h = media_h;
        double crop_w = 0.0;
        double crop_h = 0.0;
        FPDF_PAGE page = FPDF_LoadPage(DOC(), page_index);
        if (page)
        {
            int raw = FPDFPage_GetRotation(page);
            FS_RECTF bbox;
            if (FPDF_GetPageBoundingBox(page, &bbox))
            {
                crop_w = bbox.right - bbox.left;
                crop_h = bbox.top - bbox.bottom;
            }
            effective_w = FPDF_GetPageWidth(page);
            effective_h = FPDF_GetPageHeight(page);
            FPDF_ClosePage(page);
            switch (raw & 3)
            {
            case 1:
                intrinsic_rotation = 90;
                break;
            case 2:
                intrinsic_rotation = 180;
                break;
            case 3:
                intrinsic_rotation = 270;
                break;
            default:
                intrinsic_rotation = 0;
                break;
            }
        }
        PageInfo info;
        info.media_width_pts = media_w;
        info.media_height_pts = media_h;
        info.intrinsic_rotation = intrinsic_rotation;
        info.crop_width_pts = crop_w;
        info.crop_height_pts = crop_h;
        info.effective_width_pts = effective_w;
        info.effective_height_pts = effective_h;
        info.page_label = page_label(page_index);
        return info;
    }
    std::vector<PageInfo> PDFRenderer::all_page_info() const
    {
        std::vector<PageInfo> result;
        if (!doc_)
        {
            return result;
        }
        const int n = page_count();
        result.reserve(static_cast<size_t>(n));
        for (int i = 0; i < n; ++i)
        {
            auto info = page_info(i);
            if (info)
            {
                result.push_back(*info);
            }
        }
        return result;
    }
    std::vector<std::tuple<float, float, float, float>> PDFRenderer::extract_path_segments(
        int page_index) const
    {
        std::vector<std::tuple<float, float, float, float>> result;
        if (!doc_ || page_index < 0 || page_index >= page_count())
        {
            return result;
        }
        FPDF_PAGE page = FPDF_LoadPage(DOC(), page_index);
        if (!page)
        {
            return result;
        }
        const int object_count = FPDFPage_CountObjects(page);
        for (int object_index = 0; object_index < object_count; ++object_index)
        {
            FPDF_PAGEOBJECT object = FPDFPage_GetObject(page, object_index);
            if (!object || FPDFPageObj_GetType(object) != FPDF_PAGEOBJ_PATH)
            {
                continue;
            }
            FS_MATRIX matrix{1.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f};
            FPDFPageObj_GetMatrix(object, &matrix);
            auto map_point = [&matrix](float x, float y)
            {
                return std::pair<float, float>{
                    matrix.a * x + matrix.c * y + matrix.e,
                    matrix.b * x + matrix.d * y + matrix.f,
                };
            };
            const int segment_count = FPDFPath_CountSegments(object);
            bool has_current = false;
            bool has_subpath_start = false;
            float current_x = 0.0f;
            float current_y = 0.0f;
            float subpath_start_x = 0.0f;
            float subpath_start_y = 0.0f;
            for (int segment_index = 0; segment_index < segment_count; ++segment_index)
            {
                FPDF_PATHSEGMENT segment = FPDFPath_GetPathSegment(
                    object, segment_index);
                if (!segment)
                {
                    continue;
                }
                float x = 0.0f;
                float y = 0.0f;
                if (!FPDFPathSegment_GetPoint(segment, &x, &y))
                {
                    continue;
                }
                auto [mapped_x, mapped_y] = map_point(x, y);
                const int type = FPDFPathSegment_GetType(segment);
                if (type == FPDF_SEGMENT_MOVETO)
                {
                    current_x = mapped_x;
                    current_y = mapped_y;
                    subpath_start_x = mapped_x;
                    subpath_start_y = mapped_y;
                    has_current = true;
                    has_subpath_start = true;
                }
                else if (type == FPDF_SEGMENT_LINETO)
                {
                    if (has_current)
                    {
                        result.emplace_back(current_x, current_y, mapped_x, mapped_y);
                    }
                    current_x = mapped_x;
                    current_y = mapped_y;
                    has_current = true;
                }
                else
                {
                    current_x = mapped_x;
                    current_y = mapped_y;
                    has_current = true;
                }
                if (
                    FPDFPathSegment_GetClose(segment) &&
                    has_current &&
                    has_subpath_start &&
                    (current_x != subpath_start_x || current_y != subpath_start_y))
                {
                    result.emplace_back(
                        current_x,
                        current_y,
                        subpath_start_x,
                        subpath_start_y);
                    current_x = subpath_start_x;
                    current_y = subpath_start_y;
                }
            }
        }
        FPDF_ClosePage(page);
        return result;
    }

    std::vector<PDFTextRun> PDFRenderer::extract_text_runs(int page_index) const
    {
        std::vector<PDFTextRun> result;
        if (!doc_ || page_index < 0 || page_index >= page_count())
        {
            return result;
        }
        FPDF_PAGE page = FPDF_LoadPage(DOC(), page_index);
        if (!page)
        {
            return result;
        }
        FPDF_TEXTPAGE text_page = FPDFText_LoadPage(page);
        if (!text_page)
        {
            FPDF_ClosePage(page);
            return result;
        }

        PDFTextRun current;
        current.page_index = page_index;
        bool has_current = false;

        auto finish_run = [&]()
        {
            if (has_current && !current.text.empty())
            {
                result.push_back(current);
            }
            current = PDFTextRun{};
            current.page_index = page_index;
            has_current = false;
        };

        const int char_count = FPDFText_CountChars(text_page);
        for (int char_index = 0; char_index < char_count; ++char_index)
        {
            const unsigned int codepoint = FPDFText_GetUnicode(text_page, char_index);
            if (is_text_separator(codepoint))
            {
                finish_run();
                continue;
            }

            double left = 0.0;
            double right = 0.0;
            double bottom = 0.0;
            double top = 0.0;
            if (!FPDFText_GetCharBox(text_page, char_index, &left, &right, &bottom, &top))
            {
                finish_run();
                continue;
            }
            if (right <= left || top <= bottom)
            {
                finish_run();
                continue;
            }

            if (!has_current)
            {
                current.text.clear();
                current.chars.clear();
                current.left = left;
                current.right = right;
                current.bottom = bottom;
                current.top = top;
                current.page_index = page_index;
                has_current = true;
            }
            else
            {
                current.left = std::min(current.left, left);
                current.right = std::max(current.right, right);
                current.bottom = std::min(current.bottom, bottom);
                current.top = std::max(current.top, top);
            }
            std::string char_text;
            append_utf8(char_text, codepoint);
            current.text += char_text;
            current.chars.push_back(
                PDFTextChar{
                    char_text,
                    left,
                    right,
                    bottom,
                    top,
                    page_index,
                });
        }
        finish_run();

        FPDFText_ClosePage(text_page);
        FPDF_ClosePage(page);
        return result;
    }

    static int normalize_user_rotation_deg(int rotation_deg)
    {
        int r = ((rotation_deg % 360) + 360) % 360;
        return (r / 90) & 3;
    }
    std::optional<RenderedPage> PDFRenderer::render_page(
        int page_index,
        float scale,
        int rotation)
    {
        if (!doc_ || page_index < 0 || page_index >= page_count())
        {
            return std::nullopt;
        }
        rotation = normalize_user_rotation_deg(rotation);
        FPDF_PAGE page = FPDF_LoadPage(DOC(), page_index);
        if (!page)
        {
            return std::nullopt;
        }
        double pdf_width = FPDF_GetPageWidth(page);
        double pdf_height = FPDF_GetPageHeight(page);
        int render_width = static_cast<int>(pdf_width * scale + 0.5);
        int render_height = static_cast<int>(pdf_height * scale + 0.5);
        if (rotation == 1 || rotation == 3)
        {
            std::swap(render_width, render_height);
        }
        if (render_width < 1)
            render_width = 1;
        if (render_height < 1)
            render_height = 1;
        int stride = render_width * 4;
        std::vector<uint8_t> pixels(static_cast<size_t>(stride) * render_height);
        FPDF_BITMAP bitmap = FPDFBitmap_CreateEx(
            render_width, render_height,
            FPDFBitmap_BGRA,
            pixels.data(),
            stride);
        if (!bitmap)
        {
            FPDF_ClosePage(page);
            return std::nullopt;
        }
        FPDFBitmap_FillRect(bitmap, 0, 0, render_width, render_height, 0xFFFFFFFF);
        FPDF_RenderPageBitmap(
            bitmap,
            page,
            0, 0,
            render_width,
            render_height,
            rotation,
            FPDF_ANNOT | FPDF_LCD_TEXT);
        FPDFBitmap_Destroy(bitmap);
        FPDF_ClosePage(page);
        RenderedPage result;
        result.pixels = std::move(pixels);
        result.width = render_width;
        result.height = render_height;
        result.stride = stride;
        return result;
    }
    std::optional<RenderedPage> PDFRenderer::render_page_region(
        int page_index,
        float scale,
        int tile_x,
        int tile_y,
        int tile_w,
        int tile_h,
        int rotation)
    {
        if (!doc_ || page_index < 0 || page_index >= page_count())
        {
            return std::nullopt;
        }
        if (tile_w < 1 || tile_h < 1)
        {
            return std::nullopt;
        }
        rotation = normalize_user_rotation_deg(rotation);
        FPDF_PAGE page = FPDF_LoadPage(DOC(), page_index);
        if (!page)
        {
            return std::nullopt;
        }
        double pdf_width = FPDF_GetPageWidth(page);
        double pdf_height = FPDF_GetPageHeight(page);
        int full_w = static_cast<int>(pdf_width * scale + 0.5);
        int full_h = static_cast<int>(pdf_height * scale + 0.5);
        if (rotation == 1 || rotation == 3)
        {
            std::swap(full_w, full_h);
        }
        if (full_w < 1)
            full_w = 1;
        if (full_h < 1)
            full_h = 1;
        int stride = tile_w * 4;
        std::vector<uint8_t> pixels(static_cast<size_t>(stride) * tile_h);
        FPDF_BITMAP bitmap = FPDFBitmap_CreateEx(
            tile_w, tile_h,
            FPDFBitmap_BGRA,
            pixels.data(),
            stride);
        if (!bitmap)
        {
            FPDF_ClosePage(page);
            return std::nullopt;
        }
        FPDFBitmap_FillRect(bitmap, 0, 0, tile_w, tile_h, 0xFFFFFFFF);
        FPDF_RenderPageBitmap(
            bitmap,
            page,
            -tile_x, -tile_y,
            full_w,
            full_h,
            rotation,
            FPDF_ANNOT | FPDF_LCD_TEXT);
        FPDFBitmap_Destroy(bitmap);
        FPDF_ClosePage(page);
        RenderedPage result;
        result.pixels = std::move(pixels);
        result.width = tile_w;
        result.height = tile_h;
        result.stride = stride;
        return result;
    }
}
