#pragma once
#include <string>
#include <tuple>
#include <vector>
#include <optional>
#include <utility>
namespace ost_pdf
{
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
        std::optional<RenderedPage> render_page(
            int page_index,
            float scale = 1.0f,
            int rotation = 0);
        std::optional<RenderedPage> render_page_region(
            int page_index,
            float scale,
            int tile_x,
            int tile_y,
            int tile_w,
            int tile_h,
            int rotation = 0);

    private:
        void *doc_ = nullptr;
        mutable std::string last_error_;
    };
    void initialize_pdfium();
    void shutdown_pdfium();
}
