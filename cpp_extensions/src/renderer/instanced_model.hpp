#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include "renderer.hpp"
namespace ost_renderer
{

    struct ModelPart
    {
        std::string name;
        std::vector<Vec3> positions;
        std::vector<Vec3> normals;
        std::vector<uint32_t> indices;
        std::vector<uint32_t> lines;
        Color color;
    };
    struct ModelComponent
    {
        std::string name;
        std::vector<ModelPart> parts;
        Box3 bounds;
    };
    struct ModelParts
    {
        std::vector<ModelComponent> components;
        Box3 bounds;
        bool has_baked_lines = false;
    };

    ModelParts parse_instanced_model(const std::string &glb_bytes, float units_per_metre);
}
