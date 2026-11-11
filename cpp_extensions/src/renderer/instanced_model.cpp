#define CGLTF_IMPLEMENTATION
#include "cgltf/cgltf.h"
#include "instanced_model.hpp"
#include <cmath>
#include <memory>
#include <stdexcept>
#include <glm/glm.hpp>
namespace ost_renderer
{
    namespace
    {
        struct DataDeleter
        {
            void operator()(cgltf_data *data) const { cgltf_free(data); }
        };
        using DataPtr = std::unique_ptr<cgltf_data, DataDeleter>;

        const cgltf_accessor *find_attribute(const cgltf_primitive &primitive, cgltf_attribute_type type)
        {
            for (cgltf_size i = 0; i < primitive.attributes_count; ++i)
                if (primitive.attributes[i].type == type && primitive.attributes[i].index == 0)
                    return primitive.attributes[i].data;
            return nullptr;
        }

        std::vector<float> unpack(const cgltf_accessor *accessor, cgltf_size components)
        {
            if (!accessor || cgltf_num_components(accessor->type) != components)
                throw std::invalid_argument("model accessor has an unexpected type");
            std::vector<float> out(accessor->count * components);
            if (cgltf_accessor_unpack_floats(accessor, out.data(), out.size()) != out.size())
                throw std::invalid_argument("model accessor could not be read");
            return out;
        }

        Vec3 to_scene(const glm::vec3 &v, float scale)
        {
            return Vec3(-v.x * scale, v.z * scale, v.y * scale);
        }

        void append_primitive(const cgltf_primitive &primitive, const glm::mat4 &world, float scale,
                              ModelPart &part, Box3 &bounds)
        {
            if (primitive.type != cgltf_primitive_type_triangles)
                return;
            const cgltf_accessor *position_accessor = find_attribute(primitive, cgltf_attribute_type_position);
            if (!position_accessor)
                throw std::invalid_argument("model primitive has no POSITION attribute");
            std::vector<float> positions = unpack(position_accessor, 3);
            std::vector<float> normals;
            if (const cgltf_accessor *normal_accessor = find_attribute(primitive, cgltf_attribute_type_normal))
                normals = unpack(normal_accessor, 3);
            const size_t vertex_count = position_accessor->count;
            std::vector<uint32_t> indices;
            if (primitive.indices)
            {
                indices.resize(primitive.indices->count);
                for (cgltf_size i = 0; i < primitive.indices->count; ++i)
                {
                    cgltf_size index = cgltf_accessor_read_index(primitive.indices, i);
                    if (index >= vertex_count)
                        throw std::invalid_argument("model index is outside the vertex array");
                    indices[i] = static_cast<uint32_t>(index);
                }
            }
            else
            {
                indices.resize(vertex_count);
                for (size_t i = 0; i < vertex_count; ++i)
                    indices[i] = static_cast<uint32_t>(i);
            }
            if (indices.size() % 3 != 0)
                throw std::invalid_argument("model index count is not a multiple of 3");
            const glm::mat3 normal_matrix = glm::transpose(glm::inverse(glm::mat3(world)));
            const uint32_t base = static_cast<uint32_t>(part.positions.size());
            for (size_t i = 0; i < vertex_count; ++i)
            {
                glm::vec4 p = world * glm::vec4(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2], 1.0f);
                Vec3 scene_point = to_scene(glm::vec3(p), scale);
                if (!std::isfinite(scene_point.x) || !std::isfinite(scene_point.y) || !std::isfinite(scene_point.z))
                    throw std::invalid_argument("model position is not finite");
                part.positions.push_back(scene_point);
                bounds.expand(scene_point);
                glm::vec3 n(0.0f, 1.0f, 0.0f);
                if (!normals.empty())
                {
                    n = normal_matrix * glm::vec3(normals[i * 3], normals[i * 3 + 1], normals[i * 3 + 2]);
                    float length = glm::length(n);
                    n = length > 1e-12f ? n / length : glm::vec3(0.0f, 1.0f, 0.0f);
                }
                part.normals.push_back(to_scene(n, 1.0f));
            }
            for (uint32_t index : indices)
                part.indices.push_back(base + index);
            if (normals.empty())
            {
                std::vector<glm::vec3> sums(vertex_count, glm::vec3(0.0f));
                for (size_t t = 0; t + 2 < indices.size(); t += 3)
                {
                    const Vec3 &a = part.positions[base + indices[t]];
                    const Vec3 &b = part.positions[base + indices[t + 1]];
                    const Vec3 &c = part.positions[base + indices[t + 2]];
                    glm::vec3 face = glm::cross(b.to_glm() - a.to_glm(), c.to_glm() - a.to_glm());
                    for (int k = 0; k < 3; ++k)
                        sums[indices[t + k]] += face;
                }
                for (size_t i = 0; i < vertex_count; ++i)
                {
                    float length = glm::length(sums[i]);
                    glm::vec3 n = length > 1e-12f ? sums[i] / length : glm::vec3(0.0f, 0.0f, 1.0f);
                    part.normals[base + i] = Vec3::from_glm(n);
                }
            }
        }
    }

    ModelParts parse_instanced_model(const std::string &glb_bytes, float units_per_metre)
    {
        if (!std::isfinite(units_per_metre) || units_per_metre <= 0.0f)
            throw std::invalid_argument("units_per_metre must be a positive number");
        if (glb_bytes.size() < 12 || glb_bytes.compare(0, 4, "glTF") != 0)
            throw std::invalid_argument("model is not a binary glTF (GLB) file");
        cgltf_options options = {};
        options.type = cgltf_file_type_glb;
        cgltf_data *raw = nullptr;
        if (cgltf_parse(&options, glb_bytes.data(), glb_bytes.size(), &raw) != cgltf_result_success)
            throw std::invalid_argument("model is not a valid binary glTF (GLB) file");
        DataPtr data(raw);
        for (cgltf_size i = 0; i < data->buffers_count; ++i)
            if (data->buffers[i].uri != nullptr)
                throw std::invalid_argument("model buffers must be embedded in the GLB");
        if (cgltf_load_buffers(&options, data.get(), nullptr) != cgltf_result_success)
            throw std::invalid_argument("model buffers could not be loaded");
        if (cgltf_validate(data.get()) != cgltf_result_success)
            throw std::invalid_argument("model failed glTF validation");

        ModelParts result;
        const size_t material_slots = data->materials_count + 1;
        std::vector<std::vector<int>> part_for_material;
        auto component_for = [&](const cgltf_node &node) -> size_t
        {
            std::string name = node.name ? node.name : "";
            for (size_t i = 0; i < result.components.size(); ++i)
                if (result.components[i].name == name)
                    return i;
            ModelComponent component;
            component.name = std::move(name);
            result.components.push_back(std::move(component));
            part_for_material.emplace_back(material_slots, -1);
            return result.components.size() - 1;
        };
        auto part_for = [&](size_t component_index, const cgltf_material *material) -> ModelPart &
        {
            std::vector<ModelPart> &parts = result.components[component_index].parts;
            std::vector<int> &slots = part_for_material[component_index];
            size_t slot = material ? static_cast<size_t>(material - data->materials) : data->materials_count;
            if (slots[slot] < 0)
            {
                ModelPart part;
                part.color = Color(0.7f, 0.7f, 0.7f, 1.0f);
                if (material)
                {
                    part.name = material->name ? material->name : "";
                    if (material->has_pbr_metallic_roughness)
                    {
                        const float *c = material->pbr_metallic_roughness.base_color_factor;
                        float alpha = material->alpha_mode == cgltf_alpha_mode_blend ? c[3] : 1.0f;
                        part.color = Color(c[0], c[1], c[2], alpha);
                    }
                }
                slots[slot] = static_cast<int>(parts.size());
                parts.push_back(std::move(part));
            }
            return parts[static_cast<size_t>(slots[slot])];
        };
        for (cgltf_size n = 0; n < data->nodes_count; ++n)
        {
            const cgltf_node &node = data->nodes[n];
            if (!node.mesh)
                continue;
            float matrix[16];
            cgltf_node_transform_world(&node, matrix);
            glm::mat4 world;
            for (int c = 0; c < 4; ++c)
                for (int r = 0; r < 4; ++r)
                    world[c][r] = matrix[c * 4 + r];
            const size_t component_index = component_for(node);
            struct PlacedPrimitive
            {
                const cgltf_accessor *positions;
                const cgltf_material *material;
                uint32_t base;
            };
            std::vector<PlacedPrimitive> placed;
            for (cgltf_size p = 0; p < node.mesh->primitives_count; ++p)
            {
                const cgltf_primitive &primitive = node.mesh->primitives[p];
                if (primitive.type != cgltf_primitive_type_triangles)
                    continue;
                ModelPart &part = part_for(component_index, primitive.material);
                placed.push_back({find_attribute(primitive, cgltf_attribute_type_position), primitive.material,
                                  static_cast<uint32_t>(part.positions.size())});
                append_primitive(primitive, world, units_per_metre, part, result.components[component_index].bounds);
            }
            for (cgltf_size p = 0; p < node.mesh->primitives_count; ++p)
            {
                const cgltf_primitive &primitive = node.mesh->primitives[p];
                if (primitive.type != cgltf_primitive_type_lines || !primitive.indices)
                    continue;
                const cgltf_accessor *positions = find_attribute(primitive, cgltf_attribute_type_position);
                for (const auto &entry : placed)
                {
                    if (!positions || entry.positions != positions || entry.material != primitive.material)
                        continue;
                    if (primitive.indices->count % 2 != 0)
                        throw std::invalid_argument("model line index count is not a multiple of 2");
                    ModelPart &part = part_for(component_index, primitive.material);
                    for (cgltf_size i = 0; i < primitive.indices->count; ++i)
                    {
                        cgltf_size index = cgltf_accessor_read_index(primitive.indices, i);
                        if (index >= positions->count)
                            throw std::invalid_argument("model line index is outside the vertex array");
                        part.lines.push_back(entry.base + static_cast<uint32_t>(index));
                    }
                    result.has_baked_lines = true;
                    break;
                }
            }
        }
        std::vector<ModelComponent> kept_components;
        for (auto &component : result.components)
        {
            std::vector<ModelPart> kept;
            for (auto &part : component.parts)
                if (!part.indices.empty())
                    kept.push_back(std::move(part));
            if (kept.empty())
                continue;
            component.parts = std::move(kept);
            result.bounds.expand(component.bounds.min);
            result.bounds.expand(component.bounds.max);
            kept_components.push_back(std::move(component));
        }
        result.components = std::move(kept_components);
        if (result.components.empty())
            throw std::invalid_argument("model has no triangles");
        return result;
    }
}
