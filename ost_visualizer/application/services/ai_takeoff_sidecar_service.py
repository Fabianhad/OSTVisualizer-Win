import ntpath
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Optional, Sequence
from ...domain.entities.ai_takeoff import (
    FINGERPRINT_OK,
    SIDECAR_LOAD_CORRUPT,
    SIDECAR_LOAD_MISSING,
    AiTakeoffSidecar,
    Assumption,
    SidecarFingerprint,
    SIDECAR_BID_CHANGED,
    SidecarWriteRefused,
    ai_takeoff_bid_key,
    compare_fingerprints,
)
from ...domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ..dtos.ai_takeoff_dtos import (
    SIDECAR_CORRUPT,
    SIDECAR_EMPTY,
    SIDECAR_OK,
    SIDECAR_REBIND_REQUIRED,
    SIDECAR_UNAVAILABLE_NO_DATABASE_GUID,
)
from ..interfaces.i_ai_takeoff_sidecar_repository import IAiTakeoffSidecarRepository

DescriptorResolver = Callable[[str], Optional[DatabaseDescriptor]]


@dataclass(frozen=True)
class SidecarContext:
    status: str
    bid_key: Optional[str] = None
    fingerprint: Optional[SidecarFingerprint] = None
    sidecar: Optional[AiTakeoffSidecar] = None


def first_pdf_source(pages: Iterable) -> str:
    for page in pages:
        if page.image_path:
            return ntpath.basename(page.image_path.replace("/", "\\"))
    return ""


def resolve_bid_key(
    bid_ref, bid, descriptor_resolver: DescriptorResolver
) -> Optional[str]:
    descriptor = descriptor_resolver(bid_ref.file_path)
    if descriptor is None:
        descriptor = DatabaseDescriptor.for_access(bid_ref.file_path)
    guid = ""
    if isinstance(descriptor.location, SqlServerDatabaseLocation):
        guid = descriptor.location.database_guid
    return ai_takeoff_bid_key(descriptor.backend, bid.uid, guid)


def load_sidecar_context(
    bid_ref,
    bid,
    pages: Sequence,
    descriptor_resolver: DescriptorResolver,
    repository: IAiTakeoffSidecarRepository,
) -> SidecarContext:
    descriptor = descriptor_resolver(bid_ref.file_path)
    if descriptor is None:
        descriptor = DatabaseDescriptor.for_access(bid_ref.file_path)
    guid = ""
    if isinstance(descriptor.location, SqlServerDatabaseLocation):
        guid = descriptor.location.database_guid
    bid_key = ai_takeoff_bid_key(descriptor.backend, bid.uid, guid)
    if bid_key is None:
        if descriptor.backend == DatabaseBackend.SQL_SERVER:
            return SidecarContext(SIDECAR_UNAVAILABLE_NO_DATABASE_GUID)
        return SidecarContext(SIDECAR_EMPTY)
    fingerprint = SidecarFingerprint(
        database_id=descriptor.database_id,
        bid_name=str(bid.name or ""),
        page_count=len(pages),
        first_page_pdf_source=first_pdf_source(pages),
    )
    load = repository.load(bid_key)
    if load.state == SIDECAR_LOAD_MISSING:
        return SidecarContext(SIDECAR_EMPTY, bid_key, fingerprint)
    if load.state == SIDECAR_LOAD_CORRUPT or load.sidecar is None:
        return SidecarContext(SIDECAR_CORRUPT, bid_key, fingerprint)
    status = compare_fingerprints(load.sidecar.fingerprint, fingerprint)
    return SidecarContext(status, bid_key, fingerprint, load.sidecar)


class AiTakeoffSidecarService:
    def __init__(
        self,
        project_data,
        repository: IAiTakeoffSidecarRepository,
        descriptor_resolver: DescriptorResolver,
    ):
        self._project_data = project_data
        self._repository = repository
        self._descriptor_resolver = descriptor_resolver

    def context(self) -> SidecarContext:
        bid_ref = self._project_data.get_current_bid_ref()
        bid = self._project_data.get_current_bid()
        if bid_ref is None or bid is None:
            return SidecarContext(SIDECAR_EMPTY)
        return load_sidecar_context(
            bid_ref,
            bid,
            self._project_data.get_all_pages(),
            self._descriptor_resolver,
            self._repository,
        )

    def bid_key(self) -> Optional[str]:
        bid_ref = self._project_data.get_current_bid_ref()
        bid = self._project_data.get_current_bid()
        if bid_ref is None or bid is None:
            return None
        return resolve_bid_key(bid_ref, bid, self._descriptor_resolver)

    def record_assumptions(self, assumptions: Sequence[Assumption]) -> str:
        context = self.context()
        if context.status == SIDECAR_EMPTY and context.bid_key and context.fingerprint:
            sidecar = AiTakeoffSidecar(context.bid_key, context.fingerprint)
        elif context.status == FINGERPRINT_OK and context.sidecar is not None:
            sidecar = context.sidecar
        else:
            raise SidecarWriteRefused(context.status)
        incoming = {item.uid: item for item in assumptions}
        kept = [incoming.pop(item.uid, item) for item in sidecar.assumptions]
        self._repository.save(
            replace(sidecar, assumptions=tuple(kept) + tuple(incoming.values()))
        )
        return SIDECAR_OK

    def rebind(self, expected_bid_key: Optional[str] = None) -> str:
        context = self.context()
        if expected_bid_key is not None and context.bid_key != expected_bid_key:
            raise SidecarWriteRefused(SIDECAR_BID_CHANGED)
        if context.status != SIDECAR_REBIND_REQUIRED or context.sidecar is None:
            raise SidecarWriteRefused(context.status)
        self._repository.save(
            replace(
                context.sidecar,
                fingerprint=replace(
                    context.sidecar.fingerprint,
                    database_id=context.fingerprint.database_id,
                ),
            )
        )
        return SIDECAR_OK
