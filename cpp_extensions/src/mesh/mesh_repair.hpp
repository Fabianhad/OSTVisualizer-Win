#pragma once
#include "mesh_data.hpp"
namespace ost_geometry
{
    bool repair_mesh(CppMeshData &mesh);
    bool remove_degenerate_faces(CppMeshData &mesh);
    bool merge_vertices(CppMeshData &mesh, double tolerance = 1e-10);
    bool remove_unreferenced_vertices(CppMeshData &mesh);
    bool is_watertight(const CppMeshData &mesh);
    bool is_valid_for_boolean(const CppMeshData &mesh);
}
