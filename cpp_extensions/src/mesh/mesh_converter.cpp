#include "mesh_converter.hpp"
#include <stdexcept>
namespace ost_geometry
{
    std::vector<std::array<double, 3>> extract_vertices(nb::object py_vertices)
    {
        std::vector<std::array<double, 3>> result;
        if (py_vertices.is_none())
        {
            return result;
        }
        nb::list vertices_list = nb::cast<nb::list>(py_vertices);
        result.reserve(vertices_list.size());
        for (auto item : vertices_list)
        {
            nb::handle vertex_handle = item;
            if (nb::len(vertex_handle) != 3)
            {
                throw std::runtime_error("Vertex must have exactly 3 components");
            }
            result.push_back({nb::cast<double>(vertex_handle[0]),
                              nb::cast<double>(vertex_handle[1]),
                              nb::cast<double>(vertex_handle[2])});
        }
        return result;
    }
    std::vector<std::array<uint32_t, 3>> extract_faces(nb::object py_faces)
    {
        std::vector<std::array<uint32_t, 3>> result;
        if (py_faces.is_none())
        {
            return result;
        }
        nb::list faces_list = nb::cast<nb::list>(py_faces);
        result.reserve(faces_list.size());
        for (auto item : faces_list)
        {
            nb::handle face_handle = item;
            if (nb::len(face_handle) != 3)
            {
                throw std::runtime_error("Face must have exactly 3 indices (triangles only)");
            }
            result.push_back({static_cast<uint32_t>(nb::cast<int>(face_handle[0])),
                              static_cast<uint32_t>(nb::cast<int>(face_handle[1])),
                              static_cast<uint32_t>(nb::cast<int>(face_handle[2]))});
        }
        return result;
    }
    std::vector<std::array<uint32_t, 2>> extract_edges(nb::object py_edges)
    {
        std::vector<std::array<uint32_t, 2>> result;
        if (py_edges.is_none())
        {
            return result;
        }
        nb::list edges_list = nb::cast<nb::list>(py_edges);
        result.reserve(edges_list.size());
        for (auto item : edges_list)
        {
            nb::handle edge_handle = item;
            if (nb::len(edge_handle) != 2)
            {
                throw std::runtime_error("Edge must have exactly 2 indices");
            }
            result.push_back({static_cast<uint32_t>(nb::cast<int>(edge_handle[0])),
                              static_cast<uint32_t>(nb::cast<int>(edge_handle[1]))});
        }
        return result;
    }
    CppMeshData from_python_meshdata(nb::object py_mesh)
    {
        CppMeshData result;
        if (py_mesh.is_none())
        {
            return result;
        }
        try
        {
            if (nb::hasattr(py_mesh, "vertices"))
            {
                result.vertices = extract_vertices(py_mesh.attr("vertices"));
            }
            if (nb::hasattr(py_mesh, "faces"))
            {
                result.faces = extract_faces(py_mesh.attr("faces"));
            }
            if (nb::hasattr(py_mesh, "edges"))
            {
                result.edges = extract_edges(py_mesh.attr("edges"));
            }
        }
        catch (const nb::python_error &e)
        {
            throw std::runtime_error(std::string("Failed to extract mesh data: ") + e.what());
        }
        return result;
    }
    nb::list vertices_to_python(const std::vector<std::array<double, 3>> &vertices)
    {
        nb::list result;
        for (const auto &v : vertices)
        {
            result.append(nb::make_tuple(v[0], v[1], v[2]));
        }
        return result;
    }
    nb::list faces_to_python(const std::vector<std::array<uint32_t, 3>> &faces)
    {
        nb::list result;
        for (const auto &f : faces)
        {
            result.append(nb::make_tuple(
                static_cast<int>(f[0]),
                static_cast<int>(f[1]),
                static_cast<int>(f[2])));
        }
        return result;
    }
    nb::list edges_to_python(const std::vector<std::array<uint32_t, 2>> &edges)
    {
        nb::list result;
        for (const auto &e : edges)
        {
            result.append(nb::make_tuple(
                static_cast<int>(e[0]),
                static_cast<int>(e[1])));
        }
        return result;
    }
    nb::dict to_python_meshdata_args(const CppMeshData &mesh)
    {
        nb::dict result;
        result["vertices"] = vertices_to_python(mesh.vertices);
        result["faces"] = faces_to_python(mesh.faces);
        result["edges"] = edges_to_python(mesh.edges);
        result["metadata"] = nb::dict();
        return result;
    }
}
