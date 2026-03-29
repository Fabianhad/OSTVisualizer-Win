cmake_minimum_required(VERSION 3.20)
project(ost_geometry VERSION 1.0.0 LANGUAGES CXX)

# =============================================================================
# Core Configuration
# =============================================================================
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)

# =============================================================================
# Dependencies
# =============================================================================

find_package(Python 3.8 REQUIRED COMPONENTS Interpreter Development.Module)

include(FetchContent)

FetchContent_Declare(
    nanobind
    GIT_REPOSITORY https://github.com/wjakob/nanobind.git
    GIT_TAG v2.4.0
)
FetchContent_MakeAvailable(nanobind)

FetchContent_Declare(
    manifold
    GIT_REPOSITORY https://github.com/elalish/manifold.git
    GIT_TAG v3.0.0
)
set(MANIFOLD_TEST OFF CACHE BOOL "" FORCE)
set(MANIFOLD_CBIND OFF CACHE BOOL "" FORCE)
set(MANIFOLD_PYBIND OFF CACHE BOOL "" FORCE)
set(MANIFOLD_EXPORT OFF CACHE BOOL "" FORCE)
set(MANIFOLD_DEBUG OFF CACHE BOOL "" FORCE)
set(MANIFOLD_PAR OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(manifold)

FetchContent_Declare(
    glm
    GIT_REPOSITORY https://github.com/g-truc/glm.git
    GIT_TAG 0.9.9.8
)
FetchContent_MakeAvailable(glm)

# PDFium - https://github.com/bblanchon/pdfium-binaries
set(PDFIUM_DIR "${CMAKE_CURRENT_SOURCE_DIR}/pdfium")

# QPDF
set(QPDF_DIR "${CMAKE_CURRENT_SOURCE_DIR}/qpdf-12.3.2-msvc64")
find_library(QPDF_LIBRARY
    NAMES qpdf libqpdf
    PATHS "${QPDF_DIR}/lib"
    NO_DEFAULT_PATH
    REQUIRED
)

# GLAD
set(GLAD_DIR "${CMAKE_CURRENT_SOURCE_DIR}/vendor/glad")
add_library(glad STATIC ${GLAD_DIR}/src/glad.c)
target_include_directories(glad PUBLIC ${GLAD_DIR}/include)

# Qt6 — override with -DQT6_DIR=... or QT6_DIR environment variable
if(NOT QT6_DIR)
    if(DEFINED ENV{QT6_DIR})
        set(QT6_DIR "$ENV{QT6_DIR}")
    else()
        set(QT6_DIR "C:/Qt/6.10.2/msvc2022_64")
    endif()
endif()

# Output root for dev copies
set(OST_ROOT "${CMAKE_SOURCE_DIR}/..")

# =============================================================================
# Compiler Options
# =============================================================================
set(COMMON_COMPILE_OPTIONS /O2 /EHsc /W3 /wd4996)
set(COMMON_COMPILE_DEFINITIONS NOMINMAX _USE_MATH_DEFINES _CRT_SECURE_NO_WARNINGS)

# =============================================================================
# Source Definitions
# =============================================================================
set(SHARED_SOURCES
    src/mesh/mesh_converter.cpp
    src/mesh/mesh_repair.cpp
)

set(GEO_SOURCES
    src/module_geometry.cpp
    src/mesh/feature_edges.cpp
    src/boolean/boolean_ops.cpp
    ${SHARED_SOURCES}
)

set(DXF_SOURCES
    src/module_dxf.cpp
    src/dxf/dxf_writer.cpp
    ${SHARED_SOURCES}
)

set(PDF_SOURCES
    src/module_pdf.cpp
    src/pdf/pdf_renderer.cpp
)

set(IMAGE_SOURCES
    src/module_image.cpp
    src/image/image_tint.cpp
)

set(PDF_WRITER_SOURCES
    src/module_pdf_writer.cpp
    src/pdf/pdf_writer.cpp
    src/pdf/bluebeam_annotation.cpp
)

set(CAB_SOURCES
    src/cab/cab_compressor.cpp
)

# =============================================================================
# Target 1: ost_geometry (3D Boolean Operations & Mesh Processing)
# =============================================================================
nanobind_add_module(ost_geometry ${GEO_SOURCES})

target_include_directories(ost_geometry PRIVATE
    src src/mesh src/boolean src/dxf
    ${manifold_SOURCE_DIR}/include
)

target_link_libraries(ost_geometry PRIVATE manifold)
target_compile_options(ost_geometry PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_geometry PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_geometry
    LIBRARY DESTINATION ost_visualizer/presentation/visualization/core
    RUNTIME DESTINATION ost_visualizer/presentation/visualization/core
)

add_custom_command(TARGET ost_geometry POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_geometry>
        ${OST_ROOT}/ost_visualizer/presentation/visualization/core/$<TARGET_FILE_NAME:ost_geometry>
)

# =============================================================================
# Target 2: ost_dxf (DXF Export)
# =============================================================================
nanobind_add_module(ost_dxf ${DXF_SOURCES})

target_include_directories(ost_dxf PRIVATE
    src src/mesh src/boolean src/dxf
    ${manifold_SOURCE_DIR}/include
)

target_link_libraries(ost_dxf PRIVATE manifold)
target_compile_options(ost_dxf PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_dxf PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_dxf
    LIBRARY DESTINATION ost_visualizer/presentation/visualization/exporters
    RUNTIME DESTINATION ost_visualizer/presentation/visualization/exporters
)

add_custom_command(TARGET ost_dxf POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_dxf>
        ${OST_ROOT}/ost_visualizer/presentation/visualization/exporters/$<TARGET_FILE_NAME:ost_dxf>
)

# =============================================================================
# Target 3: ost_earcut (Polygon Triangulation)
# =============================================================================
nanobind_add_module(ost_earcut src/module_earcut.cpp)

target_include_directories(ost_earcut PRIVATE src)
target_compile_options(ost_earcut PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_earcut PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_earcut
    LIBRARY DESTINATION ost_visualizer/presentation/visualization/core/geometry
    RUNTIME DESTINATION ost_visualizer/presentation/visualization/core/geometry
)

add_custom_command(TARGET ost_earcut POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_earcut>
        ${OST_ROOT}/ost_visualizer/presentation/visualization/core/geometry/$<TARGET_FILE_NAME:ost_earcut>
)

# =============================================================================
# Target 4: ost_pdf (PDF Rendering with PDFium)
# =============================================================================
nanobind_add_module(ost_pdf ${PDF_SOURCES})

target_include_directories(ost_pdf PRIVATE
    src src/pdf
    ${PDFIUM_DIR}/include
)

target_link_directories(ost_pdf PRIVATE ${PDFIUM_DIR}/lib)
target_link_libraries(ost_pdf PRIVATE pdfium)
target_compile_options(ost_pdf PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_pdf PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_pdf
    LIBRARY DESTINATION ost_visualizer/presentation/visualization/pdf
    RUNTIME DESTINATION ost_visualizer/presentation/visualization/pdf
)

add_custom_command(TARGET ost_pdf POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_pdf>
        ${OST_ROOT}/ost_visualizer/presentation/visualization/pdf/$<TARGET_FILE_NAME:ost_pdf>
)

# =============================================================================
# Target 5: ost_image (Image Processing)
# =============================================================================
nanobind_add_module(ost_image ${IMAGE_SOURCES})

target_include_directories(ost_image PRIVATE src src/image)
target_compile_options(ost_image PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_image PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_image
    LIBRARY DESTINATION ost_visualizer/presentation/visualization/utils
    RUNTIME DESTINATION ost_visualizer/presentation/visualization/utils
)

add_custom_command(TARGET ost_image POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_image>
        ${OST_ROOT}/ost_visualizer/presentation/visualization/utils/$<TARGET_FILE_NAME:ost_image>
)

# =============================================================================
# Target 6: ost_pdf_writer (PDF Manipulation with QPDF)
# =============================================================================
nanobind_add_module(ost_pdf_writer ${PDF_WRITER_SOURCES})

target_include_directories(ost_pdf_writer PRIVATE
    src src/pdf
    ${QPDF_DIR}/include
)

target_link_libraries(ost_pdf_writer PRIVATE ${QPDF_LIBRARY})
target_compile_options(ost_pdf_writer PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_pdf_writer PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_pdf_writer
    LIBRARY DESTINATION ost_visualizer/presentation/visualization/exporters
    RUNTIME DESTINATION ost_visualizer/presentation/visualization/exporters
)

add_custom_command(TARGET ost_pdf_writer POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_pdf_writer>
        ${OST_ROOT}/ost_visualizer/presentation/visualization/exporters/$<TARGET_FILE_NAME:ost_pdf_writer>
)

# =============================================================================
# Target 7: ost_renderer (OpenGL 3D Renderer with OIT)
# =============================================================================
nanobind_add_module(ost_renderer
    src/module_renderer.cpp
    src/renderer/renderer.cpp
)

target_include_directories(ost_renderer PRIVATE
    src src/renderer
    ${GLAD_DIR}/include
    ${glm_SOURCE_DIR}
    ${QT6_DIR}/include
    ${QT6_DIR}/include/QtCore
    ${QT6_DIR}/include/QtGui
    ${QT6_DIR}/include/QtOpenGL
)

target_link_libraries(ost_renderer PRIVATE
    glad
    ${QT6_DIR}/lib/Qt6Core.lib
    ${QT6_DIR}/lib/Qt6Gui.lib
    ${QT6_DIR}/lib/Qt6OpenGL.lib
    opengl32
)

target_compile_options(ost_renderer PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_renderer PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_renderer
    LIBRARY DESTINATION ost_visualizer/presentation/components
    RUNTIME DESTINATION ost_visualizer/presentation/components
)

add_custom_command(TARGET ost_renderer POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_renderer>
        ${OST_ROOT}/ost_visualizer/presentation/components/$<TARGET_FILE_NAME:ost_renderer>
)

# =============================================================================
# Target 8: ost_winevent (Windows Event Monitoring)
# =============================================================================
nanobind_add_module(ost_winevent src/module_winevent.cpp)

target_compile_options(ost_winevent PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_winevent PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_winevent
    LIBRARY DESTINATION ost_visualizer/infrastructure/monitoring
    RUNTIME DESTINATION ost_visualizer/infrastructure/monitoring
)

add_custom_command(TARGET ost_winevent POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_winevent>
        ${OST_ROOT}/ost_visualizer/infrastructure/monitoring/$<TARGET_FILE_NAME:ost_winevent>
)

# =============================================================================
# Target 9: ost_cab (CAB Archive Compression)
# =============================================================================
nanobind_add_module(ost_cab ${CAB_SOURCES})

target_include_directories(ost_cab PRIVATE
    src src/cab
)

target_link_libraries(ost_cab PRIVATE cabinet)
target_compile_options(ost_cab PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_cab PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_cab
    LIBRARY DESTINATION ost_visualizer/presentation/visualization/exporters
    RUNTIME DESTINATION ost_visualizer/presentation/visualization/exporters
)

add_custom_command(TARGET ost_cab POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_cab>
        ${OST_ROOT}/ost_visualizer/presentation/visualization/exporters/$<TARGET_FILE_NAME:ost_cab>
)

# =============================================================================
# Target 10: ost_geom_utils (Geometry Utilities for Hit Testing & Validation)
# =============================================================================
nanobind_add_module(ost_geom_utils
    src/module_geom_utils.cpp
    src/geom_utils/geom_utils.cpp
)

target_include_directories(ost_geom_utils PRIVATE src)
target_compile_options(ost_geom_utils PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_geom_utils PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_geom_utils
    LIBRARY DESTINATION ost_visualizer/presentation/components/plan_view/components
    RUNTIME DESTINATION ost_visualizer/presentation/components/plan_view/components
)

add_custom_command(TARGET ost_geom_utils POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_geom_utils>
        ${OST_ROOT}/ost_visualizer/presentation/components/plan_view/components/$<TARGET_FILE_NAME:ost_geom_utils>
)

# =============================================================================
# Target 11: ost_snap (2D Placement Snap Index)
# =============================================================================
nanobind_add_module(ost_snap
    src/module_snap.cpp
    src/snap/snap_index.cpp
)

target_include_directories(ost_snap PRIVATE src)
target_compile_options(ost_snap PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_snap PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_snap
    LIBRARY DESTINATION ost_visualizer/presentation/components/plan_view/components
    RUNTIME DESTINATION ost_visualizer/presentation/components/plan_view/components
)

add_custom_command(TARGET ost_snap POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_snap>
        ${OST_ROOT}/ost_visualizer/presentation/components/plan_view/components/$<TARGET_FILE_NAME:ost_snap>
)

# =============================================================================
# Target 12: ost_coord_transform (Coordinate Transformation Utilities)
# =============================================================================
nanobind_add_module(ost_coord_transform
    src/module_coord_transform.cpp
    src/coord_transform/coord_transform.cpp
)

target_include_directories(ost_coord_transform PRIVATE src)
target_compile_options(ost_coord_transform PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_coord_transform PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_coord_transform
    LIBRARY DESTINATION ost_visualizer/domain/services
    RUNTIME DESTINATION ost_visualizer/domain/services
)

add_custom_command(TARGET ost_coord_transform POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_coord_transform>
        ${OST_ROOT}/ost_visualizer/domain/services/$<TARGET_FILE_NAME:ost_coord_transform>
)

# =============================================================================
# Target 13: ost_linear_geom (Linear Geometry & Curve Generation)
# =============================================================================
nanobind_add_module(ost_linear_geom
    src/module_linear_geom.cpp
    src/linear_geom/linear_geom.cpp
)

target_include_directories(ost_linear_geom PRIVATE src)
target_compile_options(ost_linear_geom PRIVATE ${COMMON_COMPILE_OPTIONS})
target_compile_definitions(ost_linear_geom PRIVATE ${COMMON_COMPILE_DEFINITIONS})

install(TARGETS ost_linear_geom
    LIBRARY DESTINATION ost_visualizer/presentation/visualization/core/geometry
    RUNTIME DESTINATION ost_visualizer/presentation/visualization/core/geometry
)

add_custom_command(TARGET ost_linear_geom POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:ost_linear_geom>
        ${OST_ROOT}/ost_visualizer/presentation/visualization/core/geometry/$<TARGET_FILE_NAME:ost_linear_geom>
)
