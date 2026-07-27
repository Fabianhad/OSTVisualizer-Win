#include "pdf_renderer.hpp"
#include <fpdfview.h>
#include <fpdf_doc.h>
#include <fpdf_edit.h>
#include <fpdf_progressive.h>
#include <fpdf_text.h>
#include <algorithm>
#include <cmath>
#include <atomic>
#include <cstring>
#include <limits>
#include <mutex>
#include <new>
#include <stdexcept>
namespace ost_pdf
{
#define DOC() (static_cast<FPDF_DOCUMENT>(doc_))
    static std::mutex g_init_mutex;
    static bool g_initialized = false;
    void RenderCancelToken::cancel()
    {
        cancelled_.store(true);
    }
    void RenderCancelToken::reset()
    {
        cancelled_.store(false);
    }
    bool RenderCancelToken::is_cancelled() const
    {
        return cancelled_.load();
    }
    void initialize_pdfium()
    {
        std::lock_guard<std::mutex> lock(g_init_mutex);
        if (!g_initialized)
        {
            FPDF_InitLibrary();
            g_initialized = true;
        }
    }
    void shutdown_pdfium()
    {
        std::lock_guard<std::mutex> lock(g_init_mutex);
        if (g_initialized)
        {
            FPDF_DestroyLibrary();
            g_initialized = false;
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
        bool checked_pixel_dimension(double scaled_value, bool round_up, int &result)
        {
            if (!std::isfinite(scaled_value) || scaled_value <= 0.0)
            {
                return false;
            }
            double rounded = round_up
                                 ? std::ceil(scaled_value)
                                 : std::floor(scaled_value + 0.5);
            rounded = std::max(1.0, rounded);
            if (rounded > static_cast<double>(std::numeric_limits<int>::max()))
            {
                return false;
            }
            result = static_cast<int>(rounded);
            return true;
        }
        bool checked_pixel_offset(double scaled_value, int &result)
        {
            if (!std::isfinite(scaled_value) || scaled_value < 0.0)
            {
                return false;
            }
            double rounded = std::floor(scaled_value + 0.5);
            if (rounded > static_cast<double>(std::numeric_limits<int>::max()))
            {
                return false;
            }
            result = static_cast<int>(rounded);
            return true;
        }
        bool allocate_bitmap_pixels(
            int width,
            int height,
            int &stride,
            std::vector<uint8_t> &pixels)
        {
            if (width < 1 ||
                height < 1 ||
                width > std::numeric_limits<int>::max() / 4)
            {
                return false;
            }
            stride = width * 4;
            const size_t row_bytes = static_cast<size_t>(stride);
            const size_t rows = static_cast<size_t>(height);
            if (rows > std::numeric_limits<size_t>::max() / row_bytes)
            {
                return false;
            }
            try
            {
                pixels.resize(row_bytes * rows);
            }
            catch (const std::bad_alloc &)
            {
                return false;
            }
            catch (const std::length_error &)
            {
                return false;
            }
            return true;
        }
        struct PDFiumCleanup
        {
            ~PDFiumCleanup() { shutdown_pdfium(); }
        };
        static PDFiumCleanup g_cleanup;
        FPDF_BOOL need_to_pause(IFSDK_PAUSE *pause)
        {
            if (!pause || !pause->user)
            {
                return 0;
            }
            auto *token = static_cast<RenderCancelToken *>(pause->user);
            return token->is_cancelled() ? 1 : 0;
        }
        bool render_page_bitmap_progressive(
            FPDF_BITMAP bitmap,
            FPDF_PAGE page,
            int start_x,
            int start_y,
            int size_x,
            int size_y,
            int rotation,
            int flags,
            RenderCancelToken *cancel_token)
        {
            if (cancel_token && cancel_token->is_cancelled())
            {
                return false;
            }
            IFSDK_PAUSE pause{};
            pause.version = 1;
            pause.NeedToPauseNow = need_to_pause;
            pause.user = cancel_token;
            int status = FPDF_RenderPageBitmap_Start(
                bitmap,
                page,
                start_x,
                start_y,
                size_x,
                size_y,
                rotation,
                flags,
                &pause);
            while (status == FPDF_RENDER_TOBECONTINUED)
            {
                if (cancel_token && cancel_token->is_cancelled())
                {
                    break;
                }
                status = FPDF_RenderPage_Continue(page, &pause);
            }
            FPDF_RenderPage_Close(page);
            if (cancel_token && cancel_token->is_cancelled())
            {
                return false;
            }
            return status == FPDF_RENDER_DONE;
        }
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
        return render_page_impl(page_index, scale, rotation, nullptr);
    }
    std::optional<RenderedPage> PDFRenderer::render_page_cancellable(
        int page_index,
        float scale,
        int rotation,
        RenderCancelToken &cancel_token)
    {
        return render_page_impl(page_index, scale, rotation, &cancel_token);
    }
    std::optional<RenderedPage> PDFRenderer::render_page_impl(
        int page_index,
        float scale,
        int rotation,
        RenderCancelToken *cancel_token)
    {
        if (!doc_ || page_index < 0 || page_index >= page_count())
        {
            return std::nullopt;
        }
        if (!std::isfinite(scale) || scale <= 0.0f)
        {
            return std::nullopt;
        }
        if (cancel_token && cancel_token->is_cancelled())
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
        int render_width = 0;
        int render_height = 0;
        if (!checked_pixel_dimension(pdf_width * scale, false, render_width) ||
            !checked_pixel_dimension(pdf_height * scale, false, render_height))
        {
            FPDF_ClosePage(page);
            return std::nullopt;
        }
        if (rotation == 1 || rotation == 3)
        {
            std::swap(render_width, render_height);
        }
        int stride = 0;
        std::vector<uint8_t> pixels;
        if (!allocate_bitmap_pixels(
                render_width, render_height, stride, pixels))
        {
            FPDF_ClosePage(page);
            return std::nullopt;
        }
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
        bool rendered = render_page_bitmap_progressive(
            bitmap,
            page,
            0, 0,
            render_width,
            render_height,
            rotation,
            FPDF_ANNOT | FPDF_LCD_TEXT,
            cancel_token);
        FPDFBitmap_Destroy(bitmap);
        FPDF_ClosePage(page);
        if (!rendered)
        {
            return std::nullopt;
        }
        RenderedPage result;
        result.pixels = std::move(pixels);
        result.width = render_width;
        result.height = render_height;
        result.stride = stride;
        return result;
    }
    std::optional<RenderedPage> PDFRenderer::render_page_frame(
        int page_index,
        float scale,
        double frame_x_pts,
        double frame_y_pts,
        double frame_w_pts,
        double frame_h_pts,
        int rotation)
    {
        return render_page_frame_impl(
            page_index,
            scale,
            frame_x_pts,
            frame_y_pts,
            frame_w_pts,
            frame_h_pts,
            rotation,
            nullptr);
    }
    std::optional<RenderedPage> PDFRenderer::render_page_frame_cancellable(
        int page_index,
        float scale,
        double frame_x_pts,
        double frame_y_pts,
        double frame_w_pts,
        double frame_h_pts,
        int rotation,
        RenderCancelToken &cancel_token)
    {
        return render_page_frame_impl(
            page_index,
            scale,
            frame_x_pts,
            frame_y_pts,
            frame_w_pts,
            frame_h_pts,
            rotation,
            &cancel_token);
    }
    std::optional<RenderedPage> PDFRenderer::render_page_frame_impl(
        int page_index,
        float scale,
        double frame_x_pts,
        double frame_y_pts,
        double frame_w_pts,
        double frame_h_pts,
        int rotation,
        RenderCancelToken *cancel_token)
    {
        if (!doc_ || page_index < 0 || page_index >= page_count())
        {
            return std::nullopt;
        }
        if (!std::isfinite(scale) ||
            !std::isfinite(frame_x_pts) ||
            !std::isfinite(frame_y_pts) ||
            !std::isfinite(frame_w_pts) ||
            !std::isfinite(frame_h_pts) ||
            scale <= 0.0f ||
            frame_w_pts <= 0.0 ||
            frame_h_pts <= 0.0)
        {
            return std::nullopt;
        }
        const double frame_right = frame_x_pts + frame_w_pts;
        const double frame_bottom = frame_y_pts + frame_h_pts;
        if (!std::isfinite(frame_right) || !std::isfinite(frame_bottom))
        {
            return std::nullopt;
        }
        if (cancel_token && cancel_token->is_cancelled())
        {
            return std::nullopt;
        }
        rotation = normalize_user_rotation_deg(rotation);
        FPDF_PAGE page = FPDF_LoadPage(DOC(), page_index);
        if (!page)
        {
            return std::nullopt;
        }
        double page_w = FPDF_GetPageWidth(page);
        double page_h = FPDF_GetPageHeight(page);
        if (!std::isfinite(page_w) ||
            !std::isfinite(page_h) ||
            page_w <= 0.0 ||
            page_h <= 0.0)
        {
            FPDF_ClosePage(page);
            return std::nullopt;
        }
        double canvas_w = (rotation == 1 || rotation == 3) ? page_h : page_w;
        double canvas_h = (rotation == 1 || rotation == 3) ? page_w : page_h;
        double left = std::max(0.0, frame_x_pts);
        double top = std::max(0.0, frame_y_pts);
        double right = std::min(canvas_w, frame_right);
        double bottom = std::min(canvas_h, frame_bottom);
        double clipped_w = right - left;
        double clipped_h = bottom - top;
        if (clipped_w <= 0.0 || clipped_h <= 0.0)
        {
            FPDF_ClosePage(page);
            return std::nullopt;
        }
        int render_width = 0;
        int render_height = 0;
        int full_w = 0;
        int full_h = 0;
        if (!checked_pixel_dimension(clipped_w * scale, true, render_width) ||
            !checked_pixel_dimension(clipped_h * scale, true, render_height) ||
            !checked_pixel_dimension(page_w * scale, false, full_w) ||
            !checked_pixel_dimension(page_h * scale, false, full_h))
        {
            FPDF_ClosePage(page);
            return std::nullopt;
        }
        if (rotation == 1 || rotation == 3)
        {
            std::swap(full_w, full_h);
        }
        int offset_x = 0;
        int offset_y = 0;
        int stride = 0;
        std::vector<uint8_t> pixels;
        if (!checked_pixel_offset(left * scale, offset_x) ||
            !checked_pixel_offset(top * scale, offset_y) ||
            !allocate_bitmap_pixels(
                render_width, render_height, stride, pixels))
        {
            FPDF_ClosePage(page);
            return std::nullopt;
        }
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
        bool rendered = render_page_bitmap_progressive(
            bitmap,
            page,
            -offset_x, -offset_y,
            full_w,
            full_h,
            rotation,
            FPDF_ANNOT | FPDF_LCD_TEXT,
            cancel_token);
        FPDFBitmap_Destroy(bitmap);
        FPDF_ClosePage(page);
        if (!rendered)
        {
            return std::nullopt;
        }
        RenderedPage result;
        result.pixels = std::move(pixels);
        result.width = render_width;
        result.height = render_height;
        result.stride = stride;
        return result;
    }
}
