#include <nanobind/nanobind.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/function.h>
#include "mesh_data.hpp"
#include "mesh_converter.hpp"
#include "boolean_ops.hpp"
#include "mesh_repair.hpp"
#include "feature_edges.hpp"
#include <vector>
#include <optional>
namespace nb = nanobind;
using namespace ost_geometry;
namespace
{
    nb::list apply_boolean_operations_impl(nb::list meshes_with_metadata)
    {
        struct PositiveEntry
        {
            CppMeshData mesh;
            nb::dict metadata;
            nb::dict original_metadata;
            int condition_type;
        };
        std::vector<PositiveEntry> positives;
        std::unordered_map<int, std::vector<CppMeshData>> negatives_by_type;
        bool has_any_negative = false;
        for (auto item : meshes_with_metadata)
        {
            nb::tuple tuple_item = nb::cast<nb::tuple>(item);
            nb::object py_mesh = tuple_item[0];
            nb::dict metadata = nb::cast<nb::dict>(tuple_item[1]);
            bool is_negative = false;
            if (metadata.contains("IsNegativeQuantity"))
            {
                is_negative = nb::cast<bool>(metadata["IsNegativeQuantity"]);
            }
            int cond_type = 0;
            if (metadata.contains("condition_type"))
            {
                cond_type = nb::cast<int>(metadata["condition_type"]);
            }
            CppMeshData cpp_mesh = from_python_meshdata(py_mesh);
            if (is_negative)
            {
                negatives_by_type[cond_type].push_back(std::move(cpp_mesh));
                has_any_negative = true;
            }
            else
            {
                nb::dict original_mesh_metadata;
                if (nb::hasattr(py_mesh, "metadata"))
                {
                    original_mesh_metadata = nb::cast<nb::dict>(py_mesh.attr("metadata"));
                }
                positives.push_back({std::move(cpp_mesh), metadata, original_mesh_metadata, cond_type});
            }
        }
        if (!has_any_negative)
        {
            nb::list result;
            for (size_t i = 0; i < positives.size(); ++i)
            {
                auto args = to_python_meshdata_args(positives[i].mesh);
                if (positives[i].original_metadata.size() > 0)
                {
                    args["metadata"] = positives[i].original_metadata;
                }
                result.append(nb::make_tuple(args, positives[i].metadata));
            }
            return result;
        }
        nb::list result;
        for (size_t i = 0; i < positives.size(); ++i)
        {
            auto &entry = positives[i];
            auto neg_it = negatives_by_type.find(entry.condition_type);
            if (neg_it != negatives_by_type.end() && !neg_it->second.empty())
            {
                auto diff_result = boolean_difference_batch(entry.mesh, neg_it->second);
                if (diff_result.has_value() && diff_result->is_valid())
                {
                    remove_degenerate_faces(*diff_result);
                    diff_result->edges = extract_feature_edges(*diff_result, 0.1);
                    auto args = to_python_meshdata_args(*diff_result);
                    nb::dict result_metadata;
                    if (entry.original_metadata.size() > 0)
                    {
                        result_metadata = nb::dict(entry.original_metadata);
                    }
                    result_metadata["boolean_applied"] = true;
                    args["metadata"] = result_metadata;
                    result.append(nb::make_tuple(args, entry.metadata));
                }
            }
            else
            {
                auto args = to_python_meshdata_args(entry.mesh);
                if (entry.original_metadata.size() > 0)
                {
                    args["metadata"] = entry.original_metadata;
                }
                result.append(nb::make_tuple(args, entry.metadata));
            }
        }
        return result;
    }
    nb::object boolean_difference_py(nb::object positive, nb::object negative)
    {
        CppMeshData pos_mesh = from_python_meshdata(positive);
        CppMeshData neg_mesh = from_python_meshdata(negative);
        auto result = boolean_difference(pos_mesh, neg_mesh);
        if (result.has_value())
        {
            remove_degenerate_faces(*result);
            return to_python_meshdata_args(*result);
        }
        return nb::none();
    }
    nb::object boolean_union_py(nb::object mesh1, nb::object mesh2)
    {
        CppMeshData m1 = from_python_meshdata(mesh1);
        CppMeshData m2 = from_python_meshdata(mesh2);
        auto result = boolean_union(m1, m2);
        if (result.has_value())
        {
            remove_degenerate_faces(*result);
            return to_python_meshdata_args(*result);
        }
        return nb::none();
    }
    nb::object boolean_intersection_py(nb::object mesh1, nb::object mesh2)
    {
        CppMeshData m1 = from_python_meshdata(mesh1);
        CppMeshData m2 = from_python_meshdata(mesh2);
        auto result = boolean_intersection(m1, m2);
        if (result.has_value())
        {
            remove_degenerate_faces(*result);
            return to_python_meshdata_args(*result);
        }
        return nb::none();
    }
    nb::object repair_mesh_py(nb::object py_mesh)
    {
        CppMeshData mesh = from_python_meshdata(py_mesh);
        repair_mesh(mesh);
        return to_python_meshdata_args(mesh);
    }
    nb::object extract_feature_edges_py(nb::object py_mesh, double angle_threshold)
    {
        CppMeshData mesh = from_python_meshdata(py_mesh);
        mesh.edges = extract_feature_edges(mesh, angle_threshold);
        return to_python_meshdata_args(mesh);
    }
    bool is_valid_py(nb::object py_mesh)
    {
        CppMeshData mesh = from_python_meshdata(py_mesh);
        return mesh.is_valid();
    }
    bool is_watertight_py(nb::object py_mesh)
    {
        CppMeshData mesh = from_python_meshdata(py_mesh);
        return is_watertight(mesh);
    }
    bool is_valid_for_boolean_py(nb::object py_mesh)
    {
        CppMeshData mesh = from_python_meshdata(py_mesh);
        return is_valid_for_boolean(mesh);
    }
}
NB_MODULE(ost_geometry, m)
{
    m.doc() = R"doc(
        Native geometry operations for OST Visualizer.
        This module provides high-performance boolean mesh operations using the Manifold library.
        It is a drop-in replacement for the trimesh-based implementation.
        Main functions:
            apply_boolean_operations: Apply boolean difference between positive and negative meshes
            boolean_difference: Subtract one mesh from another
            boolean_union: Combine two meshes
            boolean_intersection: Find intersection of two meshes
            repair_mesh: Fix common mesh issues
            extract_feature_edges: Find edges with high dihedral angles
        All functions accept Python MeshData objects (or any object with .vertices, .faces, .edges attributes)
        and return dictionaries suitable for constructing new MeshData objects.
    )doc";
    m.def("apply_boolean_operations", &apply_boolean_operations_impl,
          nb::arg("meshes_with_metadata"),
          R"doc(
              Apply boolean difference operations between positive and negative meshes.
              This function matches the interface of the original trimesh-based implementation.
              Args:
                  meshes_with_metadata: List of (MeshData, metadata_dict) tuples.
                      Meshes with metadata["IsNegativeQuantity"] = True are subtracted
                      from all positive meshes.
              Returns:
                  List of (mesh_args_dict, metadata_dict) tuples.
                  The mesh_args_dict can be unpacked to create a new MeshData:
                      MeshData(**mesh_args_dict)
          )doc");
    m.def("boolean_difference", &boolean_difference_py,
          nb::arg("positive"), nb::arg("negative"),
          "Subtract negative mesh from positive mesh. Returns dict or None.");
    m.def("boolean_union", &boolean_union_py,
          nb::arg("mesh1"), nb::arg("mesh2"),
          "Combine two meshes. Returns dict or None.");
    m.def("boolean_intersection", &boolean_intersection_py,
          nb::arg("mesh1"), nb::arg("mesh2"),
          "Find intersection of two meshes. Returns dict or None.");
    m.def("repair_mesh", &repair_mesh_py,
          nb::arg("mesh"),
          "Repair mesh by merging duplicate vertices and removing degenerate faces.");
    m.def("extract_feature_edges", &extract_feature_edges_py,
          nb::arg("mesh"), nb::arg("angle_threshold") = 0.1,
          R"doc(
              Extract feature edges based on dihedral angle threshold.
              Args:
                  mesh: MeshData object
                  angle_threshold: Minimum angle (radians) to consider an edge a feature edge.
                      Default 0.1 radians (~5.7 degrees).
              Returns:
                  Dict with updated edges list.
          )doc");
    m.def("is_valid", &is_valid_py,
          nb::arg("mesh"),
          "Check if mesh has valid vertices and faces.");
    m.def("is_watertight", &is_watertight_py,
          nb::arg("mesh"),
          "Check if mesh is watertight (no boundary edges).");
    m.def("is_valid_for_boolean", &is_valid_for_boolean_py,
          nb::arg("mesh"),
          "Check if mesh is suitable for boolean operations.");
    m.attr("__version__") = "1.0.0";
}
