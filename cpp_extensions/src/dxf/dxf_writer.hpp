#pragma once
#include "mesh_data.hpp"
#include <string>
#include <vector>
#include <unordered_map>
#include <fstream>
#include <array>
#include <cstdint>
namespace ost_geometry
{
    struct RGBColor
    {
        uint8_t r, g, b;
        RGBColor() : r(255), g(255), b(255) {}
        RGBColor(uint8_t r_, uint8_t g_, uint8_t b_) : r(r_), g(g_), b(b_) {}
        int to_aci() const;
        int to_true_color() const { return (r << 16) | (g << 8) | b; }
        static RGBColor from_hex(const std::string &hex);
    };
    struct DXFLayer
    {
        std::string name;
        RGBColor color;
        int line_type;
        DXFLayer() : name("0"), color(), line_type(0) {}
        DXFLayer(const std::string &n, const RGBColor &c) : name(n), color(c), line_type(0) {}
    };
    struct DXFLine
    {
        std::array<double, 3> start;
        std::array<double, 3> end;
        std::string layer;
        DXFLine() : start{0, 0, 0}, end{0, 0, 0}, layer("0") {}
        DXFLine(const std::array<double, 3> &s, const std::array<double, 3> &e, const std::string &l)
            : start(s), end(e), layer(l) {}
    };
    struct LayeredMesh
    {
        CppMeshData mesh;
        std::string layer_name;
        LayeredMesh() = default;
        LayeredMesh(const CppMeshData &m, const std::string &layer) : mesh(m), layer_name(layer) {}
    };
    class DXFWriter
    {
    public:
        DXFWriter();
        ~DXFWriter();
        void add_layer(const std::string &name, const RGBColor &color);
        void add_layer(const std::string &name, const std::string &hex_color);
        void add_line(const std::array<double, 3> &start,
                      const std::array<double, 3> &end,
                      const std::string &layer = "0");
        void add_mesh_as_lines(const CppMeshData &mesh, const std::string &layer = "0");
        void add_meshes_as_lines(const std::vector<LayeredMesh> &meshes);
        bool save(const std::string &filepath);
        void clear();
        size_t get_line_count() const { return lines_.size(); }
        size_t get_layer_count() const { return layers_.size(); }

    private:
        std::vector<DXFLayer> layers_;
        std::vector<DXFLine> lines_;
        uint32_t handle_seed = 0x100;
        void write_header(std::ofstream &file);
        void write_tables(std::ofstream &file);
        void write_blocks(std::ofstream &file);
        void write_entities(std::ofstream &file);
        void write_eof(std::ofstream &file);
        void write_group(std::ofstream &file, int code, const std::string &value);
        void write_group(std::ofstream &file, int code, int value);
        void write_group(std::ofstream &file, int code, double value);
        static std::vector<std::array<uint32_t, 2>> generate_edges_from_faces(
            const std::vector<std::array<uint32_t, 3>> &faces);
    };
}