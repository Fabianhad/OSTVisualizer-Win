#include "dxf_writer.hpp"
#include <sstream>
#include <iomanip>
#include <cmath>
#include <set>
#include <algorithm>
namespace ost_geometry
{
    int RGBColor::to_aci() const
    {
        if (r == 255 && g == 0 && b == 0)
            return 1;
        if (r == 255 && g == 255 && b == 0)
            return 2;
        if (r == 0 && g == 255 && b == 0)
            return 3;
        if (r == 0 && g == 255 && b == 255)
            return 4;
        if (r == 0 && g == 0 && b == 255)
            return 5;
        if (r == 255 && g == 0 && b == 255)
            return 6;
        if (r == 255 && g == 255 && b == 255)
            return 7;
        if (r == 128 && g == 128 && b == 128)
            return 8;
        int ri = std::min(5, static_cast<int>(r * 6 / 256));
        int gi = std::min(5, static_cast<int>(g * 6 / 256));
        int bi = std::min(5, static_cast<int>(b * 6 / 256));
        int aci = 10 + (ri * 36) + (gi * 6) + bi;
        return std::max(1, std::min(255, aci));
    }
    RGBColor RGBColor::from_hex(const std::string &hex)
    {
        std::string h = hex;
        if (!h.empty() && h[0] == '#')
        {
            h = h.substr(1);
        }
        while (h.length() < 6)
        {
            h = "0" + h;
        }
        uint8_t r = 128, g = 128, b = 128;
        try
        {
            r = static_cast<uint8_t>(std::stoi(h.substr(0, 2), nullptr, 16));
            g = static_cast<uint8_t>(std::stoi(h.substr(2, 2), nullptr, 16));
            b = static_cast<uint8_t>(std::stoi(h.substr(4, 2), nullptr, 16));
        }
        catch (...)
        {
        }
        return RGBColor(r, g, b);
    }
    DXFWriter::DXFWriter()
    {
        layers_.push_back(DXFLayer("0", RGBColor(255, 255, 255)));
    }
    DXFWriter::~DXFWriter()
    {
        clear();
    }
    void DXFWriter::add_layer(const std::string &name, const RGBColor &color)
    {
        for (auto &layer : layers_)
        {
            if (layer.name == name)
            {
                layer.color = color;
                return;
            }
        }
        layers_.push_back(DXFLayer(name, color));
    }
    void DXFWriter::add_layer(const std::string &name, const std::string &hex_color)
    {
        add_layer(name, RGBColor::from_hex(hex_color));
    }
    void DXFWriter::add_line(const std::array<double, 3> &start,
                             const std::array<double, 3> &end,
                             const std::string &layer)
    {
        lines_.push_back(DXFLine(start, end, layer));
    }
    std::vector<std::array<uint32_t, 2>> DXFWriter::generate_edges_from_faces(
        const std::vector<std::array<uint32_t, 3>> &faces)
    {
        std::set<std::pair<uint32_t, uint32_t>> edge_set;
        for (const auto &face : faces)
        {
            for (int i = 0; i < 3; ++i)
            {
                uint32_t v1 = face[i];
                uint32_t v2 = face[(i + 1) % 3];
                if (v1 > v2)
                    std::swap(v1, v2);
                edge_set.insert({v1, v2});
            }
        }
        std::vector<std::array<uint32_t, 2>> edges;
        edges.reserve(edge_set.size());
        for (const auto &e : edge_set)
        {
            edges.push_back({e.first, e.second});
        }
        return edges;
    }
    void DXFWriter::add_mesh_as_lines(const CppMeshData &mesh, const std::string &layer)
    {
        if (!mesh.is_valid())
            return;
        const auto &vertices = mesh.vertices;
        std::vector<std::array<uint32_t, 2>> edges;
        if (!mesh.edges.empty())
        {
            edges = mesh.edges;
        }
        else
        {
            edges = generate_edges_from_faces(mesh.faces);
        }
        for (const auto &edge : edges)
        {
            if (edge[0] < vertices.size() && edge[1] < vertices.size())
            {
                add_line(vertices[edge[0]], vertices[edge[1]], layer);
            }
        }
    }
    void DXFWriter::add_meshes_as_lines(const std::vector<LayeredMesh> &meshes)
    {
        for (const auto &lm : meshes)
        {
            add_mesh_as_lines(lm.mesh, lm.layer_name);
        }
    }
    void DXFWriter::clear()
    {
        lines_.clear();
        layers_.clear();
        layers_.push_back(DXFLayer("0", RGBColor(255, 255, 255)));
    }
    void DXFWriter::write_group(std::ofstream &file, int code, const std::string &value)
    {
        file << std::setw(3) << code << "\n"
             << value << "\n";
    }
    void DXFWriter::write_group(std::ofstream &file, int code, int value)
    {
        file << std::setw(3) << code << "\n"
             << value << "\n";
    }
    void DXFWriter::write_group(std::ofstream &file, int code, double value)
    {
        file << std::setw(3) << code << "\n"
             << std::fixed << std::setprecision(6) << value << "\n";
    }
    void DXFWriter::write_header(std::ofstream &file)
    {
        double minX = 1e10, minY = 1e10, minZ = 1e10;
        double maxX = -1e10, maxY = -1e10, maxZ = -1e10;
        if (lines_.empty())
        {
            minX = minY = minZ = 0;
            maxX = maxY = maxZ = 10;
        }
        else
        {
            for (const auto &line : lines_)
            {
                for (const auto &pt : {line.start, line.end})
                {
                    minX = std::min(minX, pt[0]);
                    minY = std::min(minY, pt[1]);
                    minZ = std::min(minZ, pt[2]);
                    maxX = std::max(maxX, pt[0]);
                    maxY = std::max(maxY, pt[1]);
                    maxZ = std::max(maxZ, pt[2]);
                }
            }
        }
        write_group(file, 0, "SECTION");
        write_group(file, 2, "HEADER");
        write_group(file, 9, "$ACADVER");
        write_group(file, 1, "AC1024");
        write_group(file, 9, "$HANDSEED");
        std::stringstream ss;
        ss << std::hex << std::uppercase << (handle_seed + lines_.size() + 100);
        write_group(file, 5, ss.str());
        write_group(file, 9, "$INSUNITS");
        write_group(file, 70, 6);
        write_group(file, 9, "$EXTMIN");
        write_group(file, 10, minX);
        write_group(file, 20, minY);
        write_group(file, 30, minZ);
        write_group(file, 9, "$EXTMAX");
        write_group(file, 10, maxX);
        write_group(file, 20, maxY);
        write_group(file, 30, maxZ);
        write_group(file, 0, "ENDSEC");
    }
    void DXFWriter::write_tables(std::ofstream &file)
    {
        write_group(file, 0, "SECTION");
        write_group(file, 2, "TABLES");
        write_group(file, 0, "TABLE");
        write_group(file, 2, "VPORT");
        write_group(file, 5, "8");
        write_group(file, 330, "0");
        write_group(file, 100, "AcDbSymbolTable");
        write_group(file, 70, 1);
        write_group(file, 0, "VPORT");
        write_group(file, 5, "29");
        write_group(file, 330, "8");
        write_group(file, 100, "AcDbSymbolTableRecord");
        write_group(file, 100, "AcDbViewportTableRecord");
        write_group(file, 2, "*Active");
        write_group(file, 70, 0);
        write_group(file, 10, 0.0);
        write_group(file, 20, 0.0);
        write_group(file, 11, 1.0);
        write_group(file, 21, 1.0);
        write_group(file, 12, 0.0);
        write_group(file, 22, 0.0);
        write_group(file, 13, 0.0);
        write_group(file, 23, 0.0);
        write_group(file, 14, 10.0);
        write_group(file, 24, 10.0);
        write_group(file, 15, 10.0);
        write_group(file, 25, 10.0);
        write_group(file, 16, 0.0);
        write_group(file, 26, 0.0);
        write_group(file, 36, 1.0);
        write_group(file, 17, 0.0);
        write_group(file, 27, 0.0);
        write_group(file, 37, 0.0);
        write_group(file, 40, 1.0);
        write_group(file, 41, 1.0);
        write_group(file, 42, 50.0);
        write_group(file, 43, 0.0);
        write_group(file, 44, 0.0);
        write_group(file, 50, 0.0);
        write_group(file, 51, 0.0);
        write_group(file, 71, 0);
        write_group(file, 72, 100);
        write_group(file, 73, 1);
        write_group(file, 74, 3);
        write_group(file, 75, 0);
        write_group(file, 76, 0);
        write_group(file, 77, 0);
        write_group(file, 78, 0);
        write_group(file, 0, "ENDTAB");
        write_group(file, 0, "TABLE");
        write_group(file, 2, "LTYPE");
        write_group(file, 5, "5");
        write_group(file, 330, "0");
        write_group(file, 100, "AcDbSymbolTable");
        write_group(file, 70, 3);
        write_group(file, 0, "LTYPE");
        write_group(file, 5, "14");
        write_group(file, 330, "5");
        write_group(file, 100, "AcDbSymbolTableRecord");
        write_group(file, 100, "AcDbLinetypeTableRecord");
        write_group(file, 2, "ByBlock");
        write_group(file, 70, 0);
        write_group(file, 3, "");
        write_group(file, 72, 65);
        write_group(file, 73, 0);
        write_group(file, 40, 0.0);
        write_group(file, 0, "LTYPE");
        write_group(file, 5, "15");
        write_group(file, 330, "5");
        write_group(file, 100, "AcDbSymbolTableRecord");
        write_group(file, 100, "AcDbLinetypeTableRecord");
        write_group(file, 2, "ByLayer");
        write_group(file, 70, 0);
        write_group(file, 3, "");
        write_group(file, 72, 65);
        write_group(file, 73, 0);
        write_group(file, 40, 0.0);
        write_group(file, 0, "LTYPE");
        write_group(file, 5, "16");
        write_group(file, 330, "5");
        write_group(file, 100, "AcDbSymbolTableRecord");
        write_group(file, 100, "AcDbLinetypeTableRecord");
        write_group(file, 2, "Continuous");
        write_group(file, 70, 0);
        write_group(file, 3, "Solid line");
        write_group(file, 72, 65);
        write_group(file, 73, 0);
        write_group(file, 40, 0.0);
        write_group(file, 0, "ENDTAB");
        write_group(file, 0, "TABLE");
        write_group(file, 2, "LAYER");
        write_group(file, 5, "2");
        write_group(file, 330, "0");
        write_group(file, 100, "AcDbSymbolTable");
        write_group(file, 70, static_cast<int>(layers_.size()));
        uint32_t layer_h = 0x40;
        for (const auto &layer : layers_)
        {
            write_group(file, 0, "LAYER");
            std::stringstream hss;
            hss << std::hex << std::uppercase << layer_h++;
            write_group(file, 5, hss.str());
            write_group(file, 330, "2");
            write_group(file, 100, "AcDbSymbolTableRecord");
            write_group(file, 100, "AcDbLayerTableRecord");
            write_group(file, 2, layer.name);
            write_group(file, 70, 0);
            write_group(file, 62, layer.color.to_aci());
            write_group(file, 420, layer.color.to_true_color());
            write_group(file, 6, "Continuous");
            write_group(file, 370, -3);
            write_group(file, 390, "F");
        }
        write_group(file, 0, "ENDTAB");
        write_group(file, 0, "TABLE");
        write_group(file, 2, "STYLE");
        write_group(file, 5, "3");
        write_group(file, 330, "0");
        write_group(file, 100, "AcDbSymbolTable");
        write_group(file, 70, 1);
        write_group(file, 0, "STYLE");
        write_group(file, 5, "11");
        write_group(file, 330, "3");
        write_group(file, 100, "AcDbSymbolTableRecord");
        write_group(file, 100, "AcDbTextStyleTableRecord");
        write_group(file, 2, "Standard");
        write_group(file, 70, 0);
        write_group(file, 40, 0.0);
        write_group(file, 41, 1.0);
        write_group(file, 50, 0.0);
        write_group(file, 71, 0);
        write_group(file, 42, 2.5);
        write_group(file, 3, "txt");
        write_group(file, 4, "");
        write_group(file, 0, "ENDTAB");
        write_group(file, 0, "TABLE");
        write_group(file, 2, "VIEW");
        write_group(file, 5, "6");
        write_group(file, 330, "0");
        write_group(file, 100, "AcDbSymbolTable");
        write_group(file, 70, 0);
        write_group(file, 0, "ENDTAB");
        write_group(file, 0, "TABLE");
        write_group(file, 2, "UCS");
        write_group(file, 5, "7");
        write_group(file, 330, "0");
        write_group(file, 100, "AcDbSymbolTable");
        write_group(file, 70, 0);
        write_group(file, 0, "ENDTAB");
        write_group(file, 0, "TABLE");
        write_group(file, 2, "APPID");
        write_group(file, 5, "9");
        write_group(file, 330, "0");
        write_group(file, 100, "AcDbSymbolTable");
        write_group(file, 70, 1);
        write_group(file, 0, "APPID");
        write_group(file, 5, "12");
        write_group(file, 330, "9");
        write_group(file, 100, "AcDbSymbolTableRecord");
        write_group(file, 100, "AcDbRegAppTableRecord");
        write_group(file, 2, "ACAD");
        write_group(file, 70, 0);
        write_group(file, 0, "ENDTAB");
        write_group(file, 0, "TABLE");
        write_group(file, 2, "DIMSTYLE");
        write_group(file, 5, "A");
        write_group(file, 330, "0");
        write_group(file, 100, "AcDbSymbolTable");
        write_group(file, 70, 0);
        write_group(file, 100, "AcDbDimStyleTable");
        write_group(file, 0, "ENDTAB");
        write_group(file, 0, "TABLE");
        write_group(file, 2, "BLOCK_RECORD");
        write_group(file, 5, "1");
        write_group(file, 330, "0");
        write_group(file, 100, "AcDbSymbolTable");
        write_group(file, 70, 2);
        write_group(file, 0, "BLOCK_RECORD");
        write_group(file, 5, "1F");
        write_group(file, 330, "1");
        write_group(file, 100, "AcDbSymbolTableRecord");
        write_group(file, 100, "AcDbBlockTableRecord");
        write_group(file, 2, "*Model_Space");
        write_group(file, 340, "0");
        write_group(file, 0, "BLOCK_RECORD");
        write_group(file, 5, "1E");
        write_group(file, 330, "1");
        write_group(file, 100, "AcDbSymbolTableRecord");
        write_group(file, 100, "AcDbBlockTableRecord");
        write_group(file, 2, "*Paper_Space");
        write_group(file, 340, "0");
        write_group(file, 0, "ENDTAB");
        write_group(file, 0, "ENDSEC");
    }
    void DXFWriter::write_blocks(std::ofstream &file)
    {
        write_group(file, 0, "SECTION");
        write_group(file, 2, "BLOCKS");
        write_group(file, 0, "BLOCK");
        write_group(file, 5, "20");
        write_group(file, 330, "1F");
        write_group(file, 100, "AcDbEntity");
        write_group(file, 8, "0");
        write_group(file, 100, "AcDbBlockBegin");
        write_group(file, 2, "*Model_Space");
        write_group(file, 70, 0);
        write_group(file, 10, 0.0);
        write_group(file, 20, 0.0);
        write_group(file, 30, 0.0);
        write_group(file, 3, "*Model_Space");
        write_group(file, 1, "");
        write_group(file, 0, "ENDBLK");
        write_group(file, 5, "21");
        write_group(file, 330, "1F");
        write_group(file, 100, "AcDbEntity");
        write_group(file, 8, "0");
        write_group(file, 100, "AcDbBlockEnd");
        write_group(file, 0, "BLOCK");
        write_group(file, 5, "22");
        write_group(file, 330, "1E");
        write_group(file, 100, "AcDbEntity");
        write_group(file, 8, "0");
        write_group(file, 100, "AcDbBlockBegin");
        write_group(file, 2, "*Paper_Space");
        write_group(file, 70, 0);
        write_group(file, 10, 0.0);
        write_group(file, 20, 0.0);
        write_group(file, 30, 0.0);
        write_group(file, 3, "*Paper_Space");
        write_group(file, 1, "");
        write_group(file, 0, "ENDBLK");
        write_group(file, 5, "23");
        write_group(file, 330, "1E");
        write_group(file, 100, "AcDbEntity");
        write_group(file, 8, "0");
        write_group(file, 100, "AcDbBlockEnd");
        write_group(file, 0, "ENDSEC");
    }
    void DXFWriter::write_entities(std::ofstream &file)
    {
        write_group(file, 0, "SECTION");
        write_group(file, 2, "ENTITIES");
        uint32_t entity_h = 0x1000;
        for (const auto &line : lines_)
        {
            write_group(file, 0, "LINE");
            std::stringstream hss;
            hss << std::hex << std::uppercase << entity_h++;
            write_group(file, 5, hss.str());
            write_group(file, 330, "1F");
            write_group(file, 100, "AcDbEntity");
            write_group(file, 8, line.layer);
            write_group(file, 100, "AcDbLine");
            write_group(file, 10, line.start[0]);
            write_group(file, 20, line.start[1]);
            write_group(file, 30, line.start[2]);
            write_group(file, 11, line.end[0]);
            write_group(file, 21, line.end[1]);
            write_group(file, 31, line.end[2]);
        }
        handle_seed = entity_h;
        write_group(file, 0, "ENDSEC");
    }
    void DXFWriter::write_eof(std::ofstream &file)
    {
        write_group(file, 0, "EOF");
    }
    bool DXFWriter::save(const std::string &filepath)
    {
        std::ofstream file(filepath);
        if (!file.is_open())
            return false;
        write_header(file);
        write_group(file, 0, "SECTION");
        write_group(file, 2, "CLASSES");
        write_group(file, 0, "ENDSEC");
        write_tables(file);
        write_blocks(file);
        write_entities(file);
        write_group(file, 0, "SECTION");
        write_group(file, 2, "OBJECTS");
        write_group(file, 0, "DICTIONARY");
        write_group(file, 5, "C");
        write_group(file, 100, "AcDbDictionary");
        write_group(file, 3, "ACAD_GROUP");
        write_group(file, 350, "D");
        write_group(file, 0, "DICTIONARY");
        write_group(file, 5, "D");
        write_group(file, 330, "C");
        write_group(file, 100, "AcDbDictionary");
        write_group(file, 0, "ENDSEC");
        write_group(file, 0, "EOF");
        file.close();
        return true;
    }
}
