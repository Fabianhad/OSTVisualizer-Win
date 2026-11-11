from __future__ import annotations
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple
from ....domain.entities.tower_crane_spec import (
    TowerCraneCatalog,
    TowerCraneModel,
    default_tower_crane_spec,
)
from .tower_crane_asset import tower_crane_kit_metadata, tower_crane_parts_without_edges

logger = logging.getLogger(__name__)
TOWER_CRANE_MODELS_DIR = Path(__file__).resolve().parents[3] / "resources" / "models"
# The shipped kits, in the order [crane model=...] lists them; the first is the
# model a tag without ``model=`` gets. A new model adds its kit here (built by
# tools/prepare_tower_crane_asset.py as tower_crane_<id>.glb).
TOWER_CRANE_KIT_FILES = ("tower_crane_classic.glb", "tower_crane_liebherr.glb")
# Help > About and the HTML export print every one of these.
TOWER_CRANE_CREDIT_FIELDS = (
    "title",
    "author",
    "author_url",
    "source_url",
    "site",
    "license",
    "license_url",
    "modified",
)


@dataclass(frozen=True)
class TowerCraneKit:
    path: Path
    model: TowerCraneModel
    metadata: Mapping = field(compare=False, hash=False, repr=False)

    @property
    def credit(self) -> Dict[str, str]:
        return dict(self.metadata["credit"])

    @property
    def parts_without_edges(self) -> Tuple[str, ...]:
        return tower_crane_parts_without_edges(self.metadata)

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()


def load_tower_crane_kit(path: Path) -> TowerCraneKit:
    metadata = tower_crane_kit_metadata(path.read_bytes())
    model = TowerCraneModel.from_kit_metadata(metadata)
    if path.name != f"tower_crane_{model.id}.glb":
        raise ValueError(f"{path.name} holds model {model.id!r}")
    credit = metadata.get("credit")
    if not isinstance(credit, Mapping):
        raise ValueError(f"{path.name} has no credit")
    for field in TOWER_CRANE_CREDIT_FIELDS:
        if not isinstance(credit.get(field), str) or not credit[field]:
            raise ValueError(f"{path.name}: its credit lacks {field}")
    # Lay out the model's default crane once, so a kit missing a key the layout
    # reads is refused here rather than failing whenever its cranes are drawn.
    from .tower_crane_layout import build_tower_crane_layout

    try:
        build_tower_crane_layout(
            default_tower_crane_spec(TowerCraneCatalog((model,))), metadata
        )
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError(
            f"{path.name}: its layout data is incomplete: {error!r}"
        ) from error
    return TowerCraneKit(path, model, metadata)


@lru_cache(maxsize=1)
def tower_crane_kits() -> Tuple[TowerCraneKit, ...]:
    kits = []
    for name in TOWER_CRANE_KIT_FILES:
        try:
            kits.append(load_tower_crane_kit(TOWER_CRANE_MODELS_DIR / name))
        except (OSError, ValueError) as error:
            logger.warning("Tower crane kit %s is unusable: %s", name, error)
    return tuple(kits)


def tower_crane_kit(model_id: str) -> Optional[TowerCraneKit]:
    return next((kit for kit in tower_crane_kits() if kit.model.id == model_id), None)


@lru_cache(maxsize=1)
def tower_crane_catalog() -> TowerCraneCatalog:
    return TowerCraneCatalog(tuple(kit.model for kit in tower_crane_kits()))
