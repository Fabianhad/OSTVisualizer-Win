#pragma once
#include <atomic>
#include <string>
#include <tuple>
#include <vector>
#include <optional>
#include <utility>
#include <cstdint>
namespace ost_pdf
{
    class RenderCancelToken
    {
    public:
        void cancel();
        void reset();
        bool is_cancelled() const;

    private:
        std::atomic_bool cancelled_{false};
    };
    struct RenderedPage
    {
        std::vector<uint8_t> pixels;
        int width;
        int height;
        int stride;
    };
    struct PageInfo
    {
        double media_width_pts;
        double media_height_pts;
        double crop_width_pts;
        double crop_height_pts;
        double effective_width_pts;
        double effective_height_pts;
        int intrinsic_rotation;
        std::string page_label;
    };
    struct PDFTextChar
    {
        std::string text;
        double left;
        double right;
        double bottom;
        double top;
        int page_index;
    };
    struct PDFTextRun
    {
        std::string text;
        double left;
        double right;
        double bottom;
        double top;
        int page_index;
        std::vector<PDFTextChar> chars;
    };
    struct PDFPathItem
    {
        float x1;
        float y1;
        float x2;
        float y2;
        float stroke_width;
        std::vector<float> dash;
        uint32_t stroke_rgba;
        uint32_t fill_rgba;
        bool stroked;
        bool filled;
        bool curve;
        bool closed;
        std::string object_id;
        int subpath_index;
        int segment_index;
    };
    using PathBox = std::tuple<float, float, float, float>;
    struct PDFPathExtraction
    {
        std::vector<PDFPathItem> items;
        bool truncated;
    };
    class PDFRenderer
    {
    public:
        PDFRenderer();
        ~PDFRenderer();
        PDFRenderer(const PDFRenderer &) = delete;
        PDFRenderer &operator=(const PDFRenderer &) = delete;
        PDFRenderer(PDFRenderer &&other) noexcept;
        PDFRenderer &operator=(PDFRenderer &&other) noexcept;
        bool open(const std::string &path);
        void close();
        bool is_open() const;
        std::string get_last_error() const;
        int page_count() const;
        std::pair<double, double> page_size(int page_index) const;
        std::string page_label(int page_index) const;
        std::optional<PageInfo> page_info(int page_index) const;
        std::vector<PageInfo> all_page_info() const;
        std::vector<std::tuple<float, float, float, float>> extract_path_segments(
            int page_index) const;
        PDFPathExtraction extract_path_items(
            int page_index,
            std::size_t max_items,
            std::optional<PathBox> box = std::nullopt) const;
        std::vector<PDFTextRun> extract_text_runs(int page_index) const;
        std::optional<RenderedPage> render_page(
            int page_index,
            float scale = 1.0f,
            int rotation = 0);
        std::optional<RenderedPage> render_page_cancellable(
            int page_index,
            float scale,
            int rotation,
            RenderCancelToken &cancel_token);
        std::optional<RenderedPage> render_page_frame(
            int page_index,
            float scale,
            double frame_x_pts,
            double frame_y_pts,
            double frame_w_pts,
            double frame_h_pts,
            int rotation = 0);
        std::optional<RenderedPage> render_page_frame_cancellable(
            int page_index,
            float scale,
            double frame_x_pts,
            double frame_y_pts,
            double frame_w_pts,
            double frame_h_pts,
            int rotation,
            RenderCancelToken &cancel_token);

    private:
        std::optional<RenderedPage> render_page_impl(
            int page_index,
            float scale,
            int rotation,
            RenderCancelToken *cancel_token);
        std::optional<RenderedPage> render_page_frame_impl(
            int page_index,
            float scale,
            double frame_x_pts,
            double frame_y_pts,
            double frame_w_pts,
            double frame_h_pts,
            int rotation,
            RenderCancelToken *cancel_token);
        void *doc_ = nullptr;
        mutable std::string last_error_;
    };
    void initialize_pdfium();
    void shutdown_pdfium();
}
