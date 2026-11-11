"""Build the shipped tower crane kits from their Sketchfab originals.
Usage (from the repository root, with the project venv)::
    .\\venv\\Scripts\\python.exe tools\\prepare_tower_crane_asset.py [--model all]
Each model has a profile module that knows its source file
(``tools/tower_crane_<id>.py``; sources are not in git, see
``assets/models/README.md`` for where to download them) and writes
``ost_visualizer/resources/models/tower_crane_<id>.glb``: the crane cut into
reusable parts, one glTF node per part, which both viewers assemble from a
layout computed in Python (``tower_crane_layout.py``). The shared steps live
in ``tools/tower_crane_kit.py``:
* every source node is assigned to a part by an explicit table (an unassigned
  node fails the build); the model's own footing and ropes are dropped (the
  takeoff is the footing and every rope is generated from the layout);
* the mast, jib and counterjib are cut at their lattice bay planes. Long
  members (legs, chords, rails) are clipped; short pieces (rungs, gussets,
  diagonals) go whole to the bay that holds their centre. The tool checks
  that the model really repeats at those planes;
* textures, UVs and images are dropped; each material gets the area-weighted
  median of its base texture sampled at the UVs its triangles use. The factors
  hold display (sRGB) values on purpose: both viewers draw raw colours;
* edge lines are baked per part as glTF LINES primitives (boundary and crease
  edges, without the seams the slicing creates), so both viewers draw the
  same edges;
* positions are int16 and normals int8 through ``KHR_mesh_quantization``, each
  part about its own origin with one shared scale;
* ``asset.extras.kit`` (format version 2) carries every constant the app reads
  for that model: its id and label, the credit, pitches, defaults and limits,
  attach points and part bounds. glTF conventions are kept: metres, Y-up, jib
  along +X. Running the tool twice gives the same bytes.
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import tower_crane_classic, tower_crane_liebherr  # noqa: E402
from tools.tower_crane_kit import KIT_VERSION, MAX_BYTES, write_kit  # noqa: E402

PROFILES = {
    profile.MODEL_ID: profile for profile in (tower_crane_classic, tower_crane_liebherr)
}


def kit_metadata(profile, build_kit_data: Dict) -> Dict:
    """The kit metadata: the model's identity and credit, then its layout."""
    return {
        "version": KIT_VERSION,
        "model": {"id": profile.MODEL_ID, "label": profile.LABEL},
        "credit": dict(profile.CREDIT),
        **build_kit_data,
    }


def missing_source(model: str, source: Optional[Path] = None) -> Optional[str]:
    """Why ``model`` cannot be built because its source file is not there,
    with where to download it, or None when the file is there."""
    profile = PROFILES[model]
    path = source or profile.SOURCE
    if path.is_file():
        return None
    return (
        f"the {model} source model {path} is missing: download "
        f"\"{profile.CREDIT['title']}\" from {profile.CREDIT['source_url']} and "
        f"save it as {path} (see assets/models/README.md)"
    )


def build_kit(
    model: str, source: Optional[Path] = None, target: Optional[Path] = None
) -> dict:
    """Build one model's kit and return the report."""
    profile = PROFILES[model]
    build = profile.build(source or profile.SOURCE)
    build.kit = kit_metadata(profile, build.kit)
    report = write_kit(build, target or profile.TARGET, MAX_BYTES)
    report["model"] = model
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", choices=sorted(PROFILES) + ["all"], default="all")
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--target", type=Path, default=None)
    args = parser.parse_args(argv)
    models = sorted(PROFILES) if args.model == "all" else [args.model]
    if (args.source or args.target) and len(models) != 1:
        parser.error("--source and --target need a single --model")
    missing = [m for m in (missing_source(model, args.source) for model in models) if m]
    if missing:
        for message in missing:
            print(message, file=sys.stderr)
        return 1
    reports = [build_kit(model, args.source, args.target) for model in models]
    print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
