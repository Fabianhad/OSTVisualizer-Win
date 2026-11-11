# 3D model sources

These files are the originals of models shipped in a modified form. They are not packaged; the app loads the derived files under `ost_visualizer/resources/models`.

## tower_crane.source.glb

- Title: "Tower Crane"
- Author: Chamod (<https://sketchfab.com/Chamodp>)
- Source: <https://sketchfab.com/3d-models/tower-crane-49851dc7a51b43bda6aea06856c26a85>
- License: CC BY 4.0 (<https://creativecommons.org/licenses/by/4.0/>)

`ost_visualizer/resources/models/tower_crane_kit.glb` is built from it with:

```powershell
.\venv\Scripts\python.exe tools\prepare_tower_crane_asset.py
```

The kit is the crane cut into 18 reusable parts, one glTF node per part. Both viewers assemble a crane from those parts, following the `[crane ...]` tag in the condition notes.

Changes made by that script:

- The mast, jib and counterjib are cut at their lattice bay planes into repeatable sections. Long members (legs, chords, rails) are clipped; short pieces (rungs, gussets, diagonals) go whole to the bay that holds their centre. The mast and the jib keep two alternating bays each, because their diagonals zigzag.
- The model's own concrete footing (`Cube.073`), its tie bars and its hoist ropes are removed. The count takeoff is the footing, and the app generates every rope from a one-metre `rope` part.
- Textures, UVs and images are removed. Each material gets one flat colour: the area-weighted median of its texture, sampled at the UVs its triangles use. The glass is 50 % transparent.
- The counter-jib walkway grating (16k triangles on one plane) is replaced by a thin plate.
- Edge lines are stored per part as glTF `LINES` primitives, without the seams the cutting creates.
- Positions and normals are quantized (`KHR_mesh_quantization`), each part about its own origin with one shared scale.
- The origin is the mast axis (the centre of the four mast legs), on top of the removed footing.
- `asset.extras.kit` holds the layout data the app reads: bay pitches, attach points and part bounds.

The script fails when a source node is not assigned to a part, when the model does not repeat from bay to bay, or when its pitches differ from `ost_visualizer/domain/entities/tower_crane_spec.py`. Running it twice gives the same bytes.

The kit keeps glTF conventions: metres, Y-up, jib along +X. The app credits the model in Help > About and in HTML exports that show a crane.
