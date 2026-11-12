# 3D model sources

These files are the originals of models shipped in a modified form. They are not packaged; the app loads the derived files under `ost_visualizer/resources/models`. They are also kept out of git: `.gitignore` excludes `assets/models/*.source.glb` (`tower_crane.source.glb` was committed before that rule and is still tracked). Before building the kits, download the Liebherr source as described in [Download the Liebherr source](#download-the-liebherr-source).

Each source is cut into a tower crane kit by one script, which builds every kit (or one with `--model classic` or `--model liebherr`):

```powershell
.\venv\Scripts\python.exe tools\prepare_tower_crane_asset.py
```

A kit is the crane cut into reusable parts, one glTF node per part. Both viewers assemble a crane from those parts, following the `[crane ...]` tag in the condition notes; `[crane model=liebherr]` picks a model, and a tag without `model=` gets the first one (`classic`). The shared steps are in `tools/tower_crane_kit.py`; each model has a profile module (`tools/tower_crane_classic.py`, `tools/tower_crane_liebherr.py`) that knows its source file.

What every kit gets:

- The mast, jib and counterjib are cut at their lattice bay planes into repeatable sections. Long members (legs, chords, rails) are clipped; short pieces (rungs, gussets, diagonals) go whole to the bay that holds their centre.
- The model's own footing and ropes are removed. The count takeoff is the footing, and the app generates every rope from a one-metre `rope` part that draws no edge lines.
- Textures, UVs and images are removed. Each material gets one flat colour: the area-weighted median of its texture, sampled at the UVs its triangles use.
- Edge lines are stored per part as glTF `LINES` primitives, without the seams the cutting creates.
- A triangle lying wholly on coplanar triangles of the same part and material that face the same way (a duplicate surface, which only z-fights) is left out.
- Positions and normals are quantized (`KHR_mesh_quantization`), each part about its own origin with one shared scale.
- `asset.extras.kit` (format version 2) holds everything the app reads for that model: its id and label, the credit, bay pitches, defaults and limits for the `[crane]` keys, attach points and part bounds.

The script fails when a source node is not assigned to a part, when the model does not repeat from bay to bay, when a measured pitch moves away from the profile's expected value, or when a kit is over 1 MB. Running it twice gives the same bytes. Kits keep glTF conventions: metres, Y-up, jib along +X. The app credits each model in Help > About and in HTML exports that show it.

To add a model: save its source here (it is not committed), add its download steps below, write a profile module, run the script, add `tower_crane_<id>.glb` to `TOWER_CRANE_KIT_FILES` in `ost_visualizer/presentation/visualization/assets/tower_crane_models.py`, and add a section below. Model ids are lowercase letters and digits with single hyphens, and never change once shipped (they are written in condition notes).

## Download the Liebherr source

`liebherr_tower_crane.source.glb` is not in git. Download it once before running `tools\prepare_tower_crane_asset.py`:

1. Open <https://sketchfab.com/3d-models/liebherr-tower-crane-0f8befc223734608a5d54aad4904951f> (Sketchfab asks you to sign in before downloading).
2. Choose **Download 3D Model** and the autoconverted **GLB** format.
3. Save the file as `assets/models/liebherr_tower_crane.source.glb`.

The shipped kit was built from a 22,778,880-byte file with SHA-256 `662e6ecdd0acfc4ce826776c95d3f124886c403d8b984e384b16d81bb7d9196f`. A different download may be refused by the tool (a measurement more than 5 mm off the profile) or build a kit that differs from the shipped one, which fails the test that compares them.

Without the file, the tool stops and prints where to download it, and the tests that read the source are skipped.

Credit, as the license requires: "Liebherr tower crane" by Cem Alagozlu (<https://sketchfab.com/cem.alagozlu>), from <https://sketchfab.com/3d-models/liebherr-tower-crane-0f8befc223734608a5d54aad4904951f>, licensed under CC BY 4.0 (<https://creativecommons.org/licenses/by/4.0/>). The app shows it in Help > About and in HTML exports that include the Liebherr crane.

## tower_crane.source.glb

- Title: "Tower Crane"
- Author: Chamod (<https://sketchfab.com/Chamodp>)
- Source: <https://sketchfab.com/3d-models/tower-crane-49851dc7a51b43bda6aea06856c26a85>
- License: CC BY 4.0 (<https://creativecommons.org/licenses/by/4.0/>)

Builds `ost_visualizer/resources/models/tower_crane_classic.glb`, model `classic` (19 parts). Changes:

- The mast and the jib keep two alternating bays each, because their diagonals zigzag. The jib has two tips: the modelled one, whose side braces fall, follows `jib_a`; `jib_tip_b`, the same tip with its braces turned to climb, follows `jib_b`, so the zigzag continues for odd and even jib counts (`tip_cycle` in the kit metadata).
- The counterjib root takes in the modelled section next to the mast, which is not shaped like the others (its rails and chords sit about 1 in off them), so the root meets a regular section. `[crane counterjib=N]` keeps its meaning (7 by default, 2 to 12): the kit records `root_sections: 1` and the layout places one repeated section fewer, so each N draws the same length as before.
- The concrete footing (`Cube.073`), the tie bars and the hoist ropes are removed.
- The glass is 50 % transparent.
- The yellow steel (the `material` and `frame` materials) is painted #edcf0c; the glass and concrete keep the colours every kit shares (`tools/tower_crane_kit.py`).
- The counter-jib walkway grating (16k triangles on one plane) is replaced by a thin plate.
- The origin is the mast axis (the centre of the four mast legs), on top of the removed footing.

## liebherr_tower_crane.source.glb

- Title: "Liebherr tower crane"
- Author: Cem Alagozlu (<https://sketchfab.com/cem.alagozlu>)
- Source: <https://sketchfab.com/3d-models/liebherr-tower-crane-0f8befc223734608a5d54aad4904951f>
- License: CC BY 4.0 (<https://creativecommons.org/licenses/by/4.0/>)

Builds `ost_visualizer/resources/models/tower_crane_liebherr.glb`, model `liebherr` (16 parts: one mast bay and one jib bay repeat). Changes:

- Turned a quarter turn about Y: the source's jib runs along +Z.
- The origin is the mast axis (the centre of the first mast section) at the bottom of the base block, so the base sits on top of the footing.
- Scaled by 1.6 (`KIT_SCALE` in `tools/tower_crane_liebherr.py`). The source is modelled at about 0.62 of real size: its ladder rungs are 6.5 in apart (real: about 12 in), its guardrails 2.3 to 2.7 ft high (real: 3.5 ft), its cab 4.4 ft tall and its mast 3.3 ft wide (a Liebherr 150 EC-B cab is 2.35 m tall and its smallest tower system 1.6 m wide). Scaled, those parts come within about 15 % of real values, mostly closer. The lengths below are kit metres, after the scale; the profile writes source measurements as `_m(x)`, which is x times the scale.
- The 19 identical mast sections (2.6486 m pitch, overlapping by 0.51 m) are cut at their pitch.
- Jib bays are 2.0567 m. The side diagonals zigzag every 1.6019 m, which does not repeat with the bay (about 0.46 m off at a bay joint), so one modelled V is stretched along the jib to one V per bay.
- Counterjib sections are 1.3457 m (8 regular bays). The walkway panels (3.23 m) do not repeat with them and become two plates (one per deck layer), each running 0.03 m into the root so it continues there with no open end; one mid-run frame is removed, and the section it sat in is left out of the repeat check.
- The slewing deck and ring, the head, the jib (with its trolley, hook block, lug and hoist rope) and the counterjib are each moved across the crane onto the mast axis; the source has them 0.6 to 2.2 in off it (the jib to one side, the deck to the other). Each offset is measured from the pieces that mirror each other across the crane at least 1 m apart (`lateral_centre`), and the build stops when one moves more than 5 mm from the profile's value. The head's base legs, which stand on the deck, and the rest of the head are measured and moved separately, which also closes the 2.9 in step the source has between them. The attach points (apex pin, jib pendant, hoist rope, winch lead) move with their parts.
- Defaults and limits are set by the profile, not taken from the source's own counts. The default crane is 12 mast, 21 jib and 2 counterjib sections (a 44.95 m reach on a 31.78 m mast) with a 31 ft hook rope. The limits are 4 to 24 mast sections (a highest hook of 67.2 m), 11 to 29 jib sections (a 24.4 to 61.4 m reach, within the 150 EC-B's 62.5 m) and 1 to 6 counterjib sections.
- The coiled rope on the two winch drums (about 90k triangles) becomes plain drums; the jib walkway grating becomes a plate.
- The pendant chains, the hoist ropes and the trolley rope are removed. The ropes get their own dark material. All three pendants hang on one pin between the two apex plates. Their first links and the jib chain's apex fitting are removed with the chains, so the generated pendant ropes start at the centre of that pin. Each counterjib pendant ended in a strut down to a pin on the deck edge; the strut is removed too, the generated rope runs to its foot and the pins are the counterjib lugs.
- Colours are set by the profile, not sampled: the source's yellows (its mast, slewing ring, counterjib and the rest each sampled a different shade) all become #edcf0c like the classic kit's steel. The operator cab (the piece of `Plane002` standing on the slewing deck under the jib) is white, and its windows (the faces its texture paints as glass) use the classic kit's glass. The counterweight (the concrete block hanging below the counterjib end) uses the classic kit's concrete. The base keeps its sampled grey.
