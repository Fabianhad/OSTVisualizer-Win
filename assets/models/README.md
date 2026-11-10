# 3D model sources

These files are the originals of models shipped in a modified form. They are not packaged; the app loads the derived files under `ost_visualizer/resources/models`.

## tower_crane.source.glb

- Title: "Tower Crane"
- Author: Chamod (<https://sketchfab.com/Chamodp>)
- Source: <https://sketchfab.com/3d-models/tower-crane-49851dc7a51b43bda6aea06856c26a85>
- License: CC BY 4.0 (<https://creativecommons.org/licenses/by/4.0/>)

`ost_visualizer/resources/models/tower_crane.glb` is built from it with:

```powershell
.\venv\Scripts\python.exe tools\prepare_tower_crane_asset.py
```

Changes made by that script:

- The model's own concrete footing (`Cube.073`) is removed. The count takeoff is the footing.
- Textures, UVs and images are removed. Each material gets one flat colour: the area-weighted median of its texture, sampled at the UVs its triangles use. The glass is 50 % transparent.
- The counter-jib walkway grating (16k triangles on one plane) is replaced by a thin plate.
- Primitives are merged per material and welded. Positions and normals are quantized (`KHR_mesh_quantization`).
- The origin is moved to the base of the mast, on top of the removed footing.

The derived file keeps glTF conventions: metres, Y-up, jib along +X. The app credits the model in Help > About and in HTML exports that show a crane.
