# MDB Domain Migration Plan

## Summary

This plan turns the MDB boundary diagnosis in
`docs/architecture/mdb_domain_boundary_report.md` into an incremental migration
roadmap. The target architecture keeps existing `.mdb` compatibility mandatory
while making MDB an infrastructure persistence adapter instead of the shape of
the domain and application model.

The migration should be small, reversible, and test-led. The first step is this
documentation-only plan. Later implementation steps should preserve current
read, write, schema creation, and export behavior unless a change is explicitly
covered by compatibility tests.

Target boundary:

```text
presentation
    -> application use cases and DTOs
        -> domain aggregates, entities, value objects, factories
            <- application ports
                <- infrastructure/mdb adapter
```

In this target, the domain/application model owns OSTVisualizer concepts such as
bids, pages, conditions, takeoffs, annotations, layers, visibility, and
placement rules. MDB tables, columns, optional schema quirks, raw export table
ordering, and legacy repair/defaulting logic live at infrastructure or explicit
mapping boundaries.

## Migration Principles

- Keep existing `.mdb` files readable and writable throughout the migration.
- Avoid big-bang rewrites. Move one narrow concept at a time.
- Add compatibility aliases before removing or renaming existing interfaces.
- Add or confirm golden tests before moving behavior that repairs old schemas.
- Keep persistence-neutral application ports beside existing MDB-named ports
  until all call sites migrate.
- Keep schema creator changes aligned with reader/writer compatibility tests.
- Move behavior only when the receiving domain helper, mapper, or aggregate has
  focused tests.
- Prefer explicit mapper/factory boundaries over UI or application patch logic.
- Do not use architecture cleanup to change feature behavior, UID generation,
  layer visibility performance, or raw export ordering.

## Current Pain Points Being Addressed

- `ost_visualizer/domain/ost_schema.py` contains raw MDB table names, so the
  domain layer owns persistence schema vocabulary.
- Application ports such as `IMdbReader`, `IMdbWriter`, and
  `IMdbConnectionManager` expose MDB as the application abstraction.
- MDB repair and defaulting logic is scattered across readers, schema
  compatibility helpers, writer assumptions, creation paths, and some
  presentation paths.
- `database_creator.py` is a separate source of schema truth instead of sharing
  a contract with runtime readers and writers.
- `ProjectDataService` behaves like an in-memory database facade and directly
  mutates many row-shaped entities.
- Some UI/export code imports raw schema names or table-order details.
- Layer identity, annotation defaults, reserved layers, and visibility rules are
  spread across infrastructure, domain services, and presentation.

## Phase 0: Baseline Tests and Fixtures

**Status**

Complete for the first baseline chunk.

**Goal**

Establish compatibility coverage before moving any boundary. This phase should
make current behavior observable, especially for legacy and partial MDB schemas.

**Files/areas affected**

- `tests/` MDB reader, writer, schema, layer, annotation, and export tests.
- Test fixture directories that already hold sample `.mdb` or fixture data.
- Documentation notes only when no new fixture is added.

**Exact type of changes**

- Inventory existing MDB/schema tests and identify the smallest baseline suite
  that must pass before and after each migration phase.
- Add golden fixtures only for uncovered compatibility cases that are already
  supported by production code.
- Capture expected behavior for missing optional columns, missing optional
  tables, default layers, annotation layer repair, page image layer visibility,
  and raw export ordering.
- Keep application behavior unchanged.

**Risks**

- Fixtures can be too broad or brittle if they encode incidental ordering.
- MDB fixtures can be hard to update if the Access schema is not documented.
- Tests that use real MDB files may be slower than unit-level mapper tests.

**Validation/tests needed**

- Existing MDB/schema reader and writer tests.
- Existing annotation/layer/condition visibility tests when layer fixtures are
  touched.
- Raw export golden tests if export ordering is captured.
- `git diff --check`.

**Expected end state**

- The team has a named baseline validation set for MDB compatibility.
- Later migration phases can prove they preserved compatibility.
- No production code has changed.

**Rollback/compatibility notes**

- Fixture-only changes can be reverted independently.
- If a fixture exposes an existing bug, document it before changing behavior.

**Completed work**

- Added `tests/test_mdb_schema_compatibility.py` with direct unit coverage for
  the MDB schema compatibility seam:
  - existing optional columns use the real column expression,
  - missing optional columns use the SQL default and record the compatibility
    report entry,
  - missing optional tables record a schema note,
  - missing required columns raise `UnsupportedMdbSchemaError` and record the
    missing column,
  - `order_by_existing(...)` uses available columns or the supplied fallback.
- Confirmed there are no committed real `.mdb`/`.accdb` test fixtures under
  `tests/`, so this phase uses lightweight fake cursor/connection coverage
  instead of inventing a binary fixture.
- Kept production behavior unchanged.

**Decisions made**

- Treat `MdbSchemaInspector` behavior as the first compatibility baseline
  because later schema-contract and mapper phases depend on preserving optional
  table/column handling.
- Defer golden MDB fixture creation until a later phase needs a concrete legacy
  schema sample or a known MDB file can be safely added.

**Files changed**

- `tests/test_mdb_schema_compatibility.py`
- `docs/architecture/mdb_domain_migration_plan.md`

**Validation results**

- `.\venv\Scripts\python.exe -m py_compile tests\test_mdb_schema_compatibility.py`
  passed.
- `.\venv\Scripts\python.exe -m unittest tests.test_mdb_schema_compatibility -v`
  passed: 5 tests.
- `.\venv\Scripts\python.exe -m unittest tests.test_file_project_repository tests.test_infrastructure_lifecycle -v`
  passed: 8 tests.
- `.\venv\Scripts\python.exe tools\check_architecture.py --changed-only`
  passed.
- `git diff --check` passed with only pre-existing CRLF normalization warnings
  for unrelated dirty tracked files.
- `.\venv\Scripts\python.exe -m unittest discover -s tests -v` ran 969 tests
  with the two known unrelated tuple-vs-list failures in
  `tests/test_viewer_sync_coordinator_overlay_refresh.py`:
  `test_named_view_rename_uses_inline_edit_without_text_toolbar` and
  `test_selected_annotation_style_change_updates_only_selected_annotation`.

**Remaining tasks**

- Use this baseline before each later phase.
- Add real legacy/partial MDB fixtures only when a phase needs fixture-level
  coverage that cannot be represented with focused fake-connection tests.

## Phase 1: MDB Schema Contract Boundary

**Status**

Complete for the canonical contract seam.

**Goal**

Move raw MDB schema ownership out of the domain layer while preserving all
existing import paths during the transition.

**Files/areas affected**

- `ost_visualizer/domain/ost_schema.py`
- New infrastructure contract module, for example
  `ost_visualizer/infrastructure/mdb/schema_contract.py`
- MDB reader/writer/schema creator modules.
- Export code that currently imports schema constants.
- Architecture checker allowlists if imports are adjusted.

**Exact type of changes**

- Create an MDB persistence contract module under `infrastructure/mdb`.
- Move table-section names, table names, column names, reserved/default layer
  definitions, and schema ordering constants into that module.
- Leave `domain/ost_schema.py` as a temporary compatibility re-export with a
  short deprecation comment.
- Update infrastructure imports first. Update non-infrastructure imports only
  when a neutral boundary exists.
- Do not change constant values, table ordering, or generated SQL.

**Risks**

- Import churn can produce circular imports if the new module imports domain.
- Moving constants without tests can accidentally change raw export ordering.
- Presentation may still need temporary access until Phase 7 moves export.

**Validation/tests needed**

- `.\venv\Scripts\python.exe -m py_compile` on modified Python files.
- MDB reader/writer/schema tests from Phase 0.
- Raw export tests if import paths change export code.
- `.\venv\Scripts\python.exe tools\check_architecture.py --changed-only`.
- `git diff --check`.

**Expected end state**

- MDB schema vocabulary has an infrastructure home.
- Existing code that imports `domain.ost_schema` still works through aliases.
- Domain no longer needs to be the long-term owner of raw table constants.

**Rollback/compatibility notes**

- Reverting the import move should restore the old module directly.
- Compatibility aliases must remain until all call sites are migrated.

**Completed work**

- Added `ost_visualizer/infrastructure/mdb/schema_contract.py` as the canonical
  MDB raw schema contract for OST table sections, raw table lists, and
  `singular(...)`.
- Updated `ost_visualizer/infrastructure/mdb/ost_schema.py` to re-export the new
  infrastructure contract for existing infrastructure imports.
- Updated clean infrastructure call sites to import the contract directly:
  `bid_data_reader.py`, `bid_operations.py`, `import_operations.py`, and
  `importers/ost_importer.py`.
- Left `ost_visualizer/domain/ost_schema.py` as a temporary compatibility copy
  instead of importing infrastructure, because domain-to-infrastructure imports
  violate the architecture guardrail.
- Added a parity test so the domain compatibility copy must match the
  infrastructure contract while old imports still exist.

**Decisions made**

- The infrastructure contract is canonical, but `domain/ost_schema.py` remains a
  duplicated compatibility module until presentation/export callers move behind
  later neutral boundaries.
- Do not make `domain/ost_schema.py` a literal re-export from infrastructure.
  That would satisfy the migration wording but break the enforced layer rules.
- Do not touch pre-existing dirty `components/constants.py` in this commit. Its
  existing `..ost_schema` import still resolves through the infrastructure
  compatibility module.

**Files changed**

- `ost_visualizer/infrastructure/mdb/schema_contract.py`
- `ost_visualizer/infrastructure/mdb/ost_schema.py`
- `ost_visualizer/infrastructure/mdb/components/bid_data_reader.py`
- `ost_visualizer/infrastructure/mdb/components/bid_operations.py`
- `ost_visualizer/infrastructure/mdb/components/import_operations.py`
- `ost_visualizer/infrastructure/mdb/importers/ost_importer.py`
- `ost_visualizer/domain/ost_schema.py`
- `tests/test_mdb_schema_compatibility.py`
- `docs/architecture/mdb_domain_migration_plan.md`

**Validation results**

- `.\venv\Scripts\python.exe -m py_compile ost_visualizer\infrastructure\mdb\schema_contract.py ost_visualizer\infrastructure\mdb\ost_schema.py ost_visualizer\domain\ost_schema.py ost_visualizer\infrastructure\mdb\components\bid_data_reader.py ost_visualizer\infrastructure\mdb\components\bid_operations.py ost_visualizer\infrastructure\mdb\components\import_operations.py ost_visualizer\infrastructure\mdb\importers\ost_importer.py tests\test_mdb_schema_compatibility.py`
  passed.
- `.\venv\Scripts\python.exe -m unittest tests.test_mdb_schema_compatibility tests.test_file_project_repository tests.test_infrastructure_lifecycle tests.test_import_refresh_flow -v`
  passed: 19 tests.
- `.\venv\Scripts\python.exe tools\check_architecture.py --changed-only`
  passed.
- `git diff --check` passed with only pre-existing CRLF normalization warnings
  for unrelated dirty tracked files.
- `.\venv\Scripts\python.exe -m unittest discover -s tests -v` ran 970 tests
  with the two known unrelated tuple-vs-list failures in
  `tests/test_viewer_sync_coordinator_overlay_refresh.py`:
  `test_named_view_rename_uses_inline_edit_without_text_toolbar` and
  `test_selected_annotation_style_change_updates_only_selected_annotation`.

**Remaining tasks**

- Remove the domain compatibility copy only after all non-domain callers migrate
  to neutral application/export boundaries.
- Update any currently dirty or future infrastructure call sites that still use
  `infrastructure/mdb/ost_schema.py` when those files can be safely touched.

## Phase 2: Neutral Application Ports

**Status**

Complete for the initial neutral alias seam.

**Goal**

Introduce persistence-neutral application interfaces beside MDB-named ports so
use cases can depend on project persistence rather than MDB identity.

**Files/areas affected**

- `ost_visualizer/application/interfaces/`
- Use cases that depend on `IMdbReader`, `IMdbWriter`, or
  `IMdbConnectionManager`.
- Dependency injection setup.
- Infrastructure MDB implementations.

**Exact type of changes**

- Add neutral ports such as `ProjectReadPort`, `ProjectWritePort`, and
  `ProjectStorageConnectionPort`.
- Make existing MDB implementations satisfy the neutral ports.
- Keep `IMdbReader`, `IMdbWriter`, and `IMdbConnectionManager` as aliases or
  thin derived protocols during migration.
- Migrate one use case at a time to neutral port names.
- Avoid changing method signatures until mapper boundaries exist.

**Risks**

- Renaming ports too quickly can obscure real behavior changes.
- DI registration can accidentally register duplicate or conflicting services.
- Tests may mock the old interface names directly.

**Validation/tests needed**

- Use case tests for load, save, annotation insert/update, layer persistence, and
  bid lock/write guard behavior.
- DI/container smoke tests if available.
- `.\venv\Scripts\python.exe tools\check_architecture.py --changed-only`.
- `git diff --check`.

**Expected end state**

- Application code has a neutral persistence vocabulary.
- MDB remains the active adapter, but use cases no longer need MDB-specific
  names.
- Old interface names continue to work until removed in a later cleanup.

**Rollback/compatibility notes**

- Because old ports remain as aliases, individual use case migrations can be
  reverted without changing MDB implementations.

**Completed work**

- Added neutral application port aliases:
  `ProjectReadPort`, `ProjectWritePort`, and
  `ProjectStorageConnectionPort`.
- Kept the existing `IMdbReader`, `IMdbWriter`, and `IMdbConnectionManager`
  protocols unchanged.
- Migrated `UpdateLayerShowUseCase` to depend on `ProjectWritePort` as the
  first low-risk use-case annotation.
- Added tests proving the neutral names alias the existing MDB protocols.

**Decisions made**

- Use runtime aliases instead of new `Protocol` subclasses for the first seam.
  The architecture checker requires protocol class names to start with `I`, and
  aliases avoid duplicating the large MDB method surfaces.
- Keep method signatures and DI registration unchanged in this phase.
- Migrate additional use cases gradually as nearby behavior changes are made.

**Files changed**

- `ost_visualizer/application/interfaces/project_read_port.py`
- `ost_visualizer/application/interfaces/project_write_port.py`
- `ost_visualizer/application/interfaces/project_storage_connection_port.py`
- `ost_visualizer/application/use_cases/project/update_layer_show_use_case.py`
- `tests/test_project_persistence_ports.py`
- `docs/architecture/mdb_domain_migration_plan.md`

**Validation results**

- `.\venv\Scripts\python.exe -m py_compile ost_visualizer\application\interfaces\project_read_port.py ost_visualizer\application\interfaces\project_write_port.py ost_visualizer\application\interfaces\project_storage_connection_port.py ost_visualizer\application\use_cases\project\update_layer_show_use_case.py tests\test_project_persistence_ports.py`
  passed.
- `.\venv\Scripts\python.exe -m unittest tests.test_project_persistence_ports tests.test_deferred_persistence_manager tests.test_bid_lock_permissions -v`
  passed: 78 tests.
- `.\venv\Scripts\python.exe tools\check_architecture.py --changed-only`
  passed.
- `git diff --check` passed with only pre-existing CRLF normalization warnings
  for unrelated dirty tracked files.
- First full-suite attempt exited with Windows access violation
  `-1073741819` during `test_dialog_lifecycle`; rerunning
  `tests.test_dialog_lifecycle -v` passed, so the crash was treated as an
  unrelated transient/native full-suite issue.
- Full-suite retry with
  `.\venv\Scripts\python.exe -m unittest discover -s tests -v` ran 971 tests
  with the two known unrelated tuple-vs-list failures in
  `tests/test_viewer_sync_coordinator_overlay_refresh.py`:
  `test_named_view_rename_uses_inline_edit_without_text_toolbar` and
  `test_selected_annotation_style_change_updates_only_selected_annotation`.

**Remaining tasks**

- Migrate additional use cases from `IMdbWriter`/`IMdbReader` annotations to
  neutral ports as their behavior is touched.
- Replace aliases with narrower neutral protocols only after mapper/export
  boundaries reduce the raw MDB-shaped method surfaces.

## Phase 3: MDB Mappers and Repair/Defaulting Boundary

**Status**

Complete for the first narrow mapper boundary.

**Goal**

Move legacy MDB repair and defaulting into explicit mapper/factory boundaries so
application and UI code receive valid domain objects.

**Files/areas affected**

- `ost_visualizer/infrastructure/mdb/components/*_reader.py`
- `ost_visualizer/infrastructure/mdb/components/*_operations.py`
- New mapper modules under `ost_visualizer/infrastructure/mdb/`
- Domain entities touched by mapper outputs.
- Tests for schema compatibility and legacy rows.

**Exact type of changes**

- Introduce the first mapper around one narrow concept, preferably layers or
  annotations because they already have known repair/default behavior.
- For layers, centralize reserved layer row mapping, missing layer visibility,
  and default layer name/UID repair.
- For annotations, centralize `BidLayerUID` repair, table-specific row mapping,
  and property normalization.
- Keep SQL fetching logic in readers, but move row-to-domain conversion and
  compatibility defaults into mappers.
- Add tests that call mappers directly with partial row data.
- Do not change persisted data shape or writer output yet.

**Risks**

- Moving repair logic can subtly change defaults for old MDB files.
- Annotation tables have different shapes, so over-generalizing the first mapper
  can increase risk.
- Domain entities may still expose raw property keys until later phases.

**Validation/tests needed**

- Legacy/partial MDB schema tests from Phase 0.
- Mapper unit tests for missing columns, missing layer UID, missing reserved
  layers, and optional annotation tables.
- Annotation placement and visibility tests.
- `.\venv\Scripts\python.exe -m py_compile` on modified Python files.
- `git diff --check`.

**Expected end state**

- At least one MDB concept has an explicit boundary where raw rows become valid
  domain objects.
- Repair/defaulting is no longer hidden inside UI/application paths for that
  concept.

**Rollback/compatibility notes**

- Keep old reader helper functions until mapper behavior is proven equivalent.
- Mapper extraction should be mechanical enough to revert concept-by-concept.

**Completed work**

- Added `MdbAnnotationLayerMapper` as the first MDB mapper boundary.
- Moved annotation layer repair/defaulting out of the annotation reader closure:
  explicit `BidLayerUID` rows resolve through their row layer, while annotation
  rows without `BidLayerUID` resolve to the reserved Annotation layer.
- Preserved existing fallback behavior when no Annotation layer exists:
  no layer UID and visible by default.
- Updated `annotation_reader.py` to delegate layer resolution to the mapper
  while leaving SQL fetching and row-to-annotation construction unchanged.
- Added direct mapper tests for hidden Annotation layer defaults, explicit row
  layers, and missing Annotation layer fallback.

**Decisions made**

- Start with annotation layer mapping instead of a broad annotation row mapper
  because it captures the reload-only repair rule without rewriting every
  annotation table parser.
- Keep raw annotation property dictionaries in the reader for now; those move
  later when annotation factories and export boundaries are in place.

**Files changed**

- `ost_visualizer/infrastructure/mdb/mappers/annotation_mapper.py`
- `ost_visualizer/infrastructure/mdb/components/annotation_reader.py`
- `tests/test_mdb_annotation_mapper.py`
- `docs/architecture/mdb_domain_migration_plan.md`

**Validation results**

- `.\venv\Scripts\python.exe -m py_compile ost_visualizer\infrastructure\mdb\mappers\annotation_mapper.py ost_visualizer\infrastructure\mdb\components\annotation_reader.py tests\test_mdb_annotation_mapper.py`
  passed.
- `.\venv\Scripts\python.exe -m unittest tests.test_mdb_annotation_mapper tests.test_mdb_schema_compatibility tests.test_bid_dimension_annotations -v`
  passed: 54 tests.
- `.\venv\Scripts\python.exe tools\check_architecture.py --changed-only`
  passed.
- `git diff --check` passed with only pre-existing CRLF normalization warnings
  for unrelated dirty tracked files.
- `.\venv\Scripts\python.exe -m unittest discover -s tests -v` ran 974 tests
  with the two known unrelated tuple-vs-list failures in
  `tests/test_viewer_sync_coordinator_overlay_refresh.py`:
  `test_named_view_rename_uses_inline_edit_without_text_toolbar` and
  `test_selected_annotation_style_change_updates_only_selected_annotation`.

**Remaining tasks**

- Add broader row-to-domain mappers only when a specific table group is being
  migrated and has direct compatibility tests.
- Move raw property normalization out of the reader after domain annotation
  factories exist.

## Phase 4: Schema Creator Alignment

**Status**

Complete for the first creator/contract alignment slice.

**Goal**

Make `database_creator.py` consume the same MDB persistence contract as the
runtime reader/writer path.

**Files/areas affected**

- `ost_visualizer/infrastructure/mdb/database_creator.py`
- MDB schema contract module from Phase 1.
- Schema compatibility tests.
- Tests that create a new MDB and read it back.

**Exact type of changes**

- Start with shared constants for table names, reserved layer rows, layer
  reference tables, and default values.
- Then align column definitions, indexes, and relationships where tests can
  compare expected contracts.
- Avoid rewriting SQL generation in the first creator alignment PR.
- Add tests that verify a newly created MDB can be read by current readers and
  contains expected reserved layers/defaults.

**Risks**

- Schema creator changes affect new project databases even if old databases
  still read correctly.
- SQL string generation can differ in harmless-looking ways that Access treats
  differently.
- Relationship/index changes can affect write performance or constraints.

**Validation/tests needed**

- Database creation tests.
- Read-back tests against a newly created MDB.
- Schema contract comparison tests for table/column/default-layer definitions.
- Existing reader/writer tests.
- `git diff --check`.

**Expected end state**

- Schema creator and reader/writer code share one MDB persistence contract for
  the migrated pieces.
- New MDBs and existing MDBs remain compatible.

**Rollback/compatibility notes**

- Keep changes in small groups: default layers first, then tables/columns, then
  indexes/relationships.
- Revert individual groups if generated MDB compatibility changes.

**Completed work**

- Moved the default reserved layer seed rows into
  `ost_visualizer/infrastructure/mdb/schema_contract.py` as
  `DEFAULT_LAYER_ROWS`.
- Updated `database_creator.py` to seed `BidLayers` from the shared contract.
- Added a database-creator test that monkeypatches the connection and verifies
  seeded layer names, visibility flags, lock flags, and sequence values match
  `DEFAULT_LAYER_ROWS`.
- Left table DDL, index lists, relationships, and SQL generation unchanged.

**Decisions made**

- Align default layers first because they are a cross-cutting compatibility
  concept used by layer visibility, annotation mapping, and created databases.
- Keep the creator's local `_DEFAULT_LAYERS` name as an alias to avoid a broad
  rewrite of the creator module.

**Files changed**

- `ost_visualizer/infrastructure/mdb/schema_contract.py`
- `ost_visualizer/infrastructure/mdb/database_creator.py`
- `tests/test_infrastructure_lifecycle.py`
- `docs/architecture/mdb_domain_migration_plan.md`

**Validation results**

- `.\venv\Scripts\python.exe -m py_compile ost_visualizer\infrastructure\mdb\schema_contract.py ost_visualizer\infrastructure\mdb\database_creator.py tests\test_infrastructure_lifecycle.py`
  passed.
- `.\venv\Scripts\python.exe -m unittest tests.test_infrastructure_lifecycle tests.test_mdb_schema_compatibility -v`
  passed: 14 tests.
- `.\venv\Scripts\python.exe tools\check_architecture.py --changed-only`
  passed.
- `git diff --check` passed with only pre-existing CRLF normalization warnings
  for unrelated dirty tracked files.
- `.\venv\Scripts\python.exe -m unittest discover -s tests -v` ran 975 tests
  with the two known unrelated tuple-vs-list failures in
  `tests/test_viewer_sync_coordinator_overlay_refresh.py`:
  `test_named_view_rename_uses_inline_edit_without_text_toolbar` and
  `test_selected_annotation_style_change_updates_only_selected_annotation`.

**Remaining tasks**

- Align table names, column specs, index specs, and relationship specs only when
  each group has focused read-back/schema tests.
- Add real newly-created MDB read-back coverage if Access-driver availability
  can be made reliable in the test environment.

## Phase 5: Layer and Annotation Domain Factories

**Status**

Complete.

**Goal**

Move layer identity and annotation creation invariants closer to the domain so
new objects are valid before they reach persistence or presentation refresh
paths.

**Files/areas affected**

- `ost_visualizer/domain/entities/`
- `ost_visualizer/domain/services/`
- New domain helper/factory modules if needed.
- `ProjectDataService` call sites that create layers or annotations.
- Annotation placement handlers and detached window insert paths.

**Exact type of changes**

- Add a small layer helper, for example `LayerSet`, that resolves reserved layer
  roles, layer UID ownership, and visibility by UID.
- Add annotation construction helpers that assign annotation layer identity,
  default style, text/hotlink/named-view properties, and placement metadata
  before write/model insert.
- Keep raw MDB property names out of the new domain API where possible.
- Migrate one creation path at a time while preserving existing DTOs and handler
  behavior.
- Keep presentation placement blocking behavior unchanged when the Annotation
  layer is hidden.

**Risks**

- Layer visibility bugs can return if new graphics bypass existing registration
  and visibility gates.
- Annotation tools have several variants, so missing one creation path can
  reintroduce reload-only repair.
- Factories can become too large if they absorb persistence-specific details.

**Validation/tests needed**

- Existing and newly placed annotation layer visibility tests.
- Tests for every annotation tool type receiving the annotation layer UID before
  write/model insert.
- Detached/secondary window creation tests.
- Takeoff and condition layer visibility tests.
- Tests proving the fix does not depend on the layer name alone.
- `git diff --check`.

**Expected end state**

- Layer identity and annotation creation rules have one domain-facing path.
- Newly created layer-backed graphics are valid immediately, without requiring a
  reload to repair missing layer data.

**Rollback/compatibility notes**

- Keep old construction paths until each tool type is migrated and tested.
- If a factory migration fails, revert the specific tool path instead of the
  whole phase.

**Completed work**

- Added `LayerVisibility` and `LayerSet` to
  `ost_visualizer/domain/entities/layer.py`.
- Centralized case-insensitive layer UID lookup, visibility by UID, default
  layer resolution, and Annotation-layer convenience helpers.
- Updated `MdbAnnotationLayerMapper` to use `LayerSet`, so MDB annotation layer
  repair now delegates to a domain layer-identity helper instead of duplicating
  lookup logic in infrastructure.
- Added domain tests for `LayerSet` and kept MDB annotation mapper tests passing.
- Stabilized the pre-existing layer-visibility work in commit `7894515` so the
  creation factory could be integrated on a clean tree.
- Added `AnnotationCreationFactory` beside `InsertAnnotationSpec` to centralize
  annotation-layer UID assignment for new annotation specs.
- Updated main plan-view annotation insert/paste paths and detached window
  annotation/text/named-view/hotlink paths to use that factory instead of local
  per-window assignment logic.
- Added factory tests covering missing layer assignment, existing layer
  preservation, no-annotation-layer no-op behavior, and batch assignment.

**Decisions made**

- Keep `AnnotationCreationFactory` in the application DTO boundary because it
  mutates `InsertAnnotationSpec`; placing it in domain would force domain to
  import an application DTO.
- Keep `LayerSet` small and identity-focused. It does not become a bid aggregate
  or own persistence/write behavior.
- Do not move style/default property generation out of presentation yet. That
  still carries UI tool defaults and raw legacy property keys and should move
  only with a broader annotation-property boundary.

**Files changed**

- `ost_visualizer/domain/entities/layer.py`
- `ost_visualizer/application/dtos/annotation_creation_factory.py`
- `ost_visualizer/infrastructure/mdb/mappers/annotation_mapper.py`
- `ost_visualizer/presentation/handlers/plan_view_action_handler.py`
- `ost_visualizer/presentation/windows/components/window.py`
- `tests/test_annotation_creation_factory.py`
- `tests/test_domain_layers.py`
- `docs/architecture/mdb_domain_migration_plan.md`

**Validation results**

- `.\venv\Scripts\python.exe -m py_compile ost_visualizer\domain\entities\layer.py ost_visualizer\infrastructure\mdb\mappers\annotation_mapper.py tests\test_domain_layers.py tests\test_mdb_annotation_mapper.py`
  passed.
- `.\venv\Scripts\python.exe -m unittest tests.test_domain_layers tests.test_mdb_annotation_mapper tests.test_deferred_persistence_project_state -v`
  passed: 13 tests.
- `.\venv\Scripts\python.exe -m py_compile ost_visualizer\application\dtos\annotation_creation_factory.py ost_visualizer\presentation\handlers\plan_view_action_handler.py ost_visualizer\presentation\windows\components\window.py tests\test_annotation_creation_factory.py`
  passed.
- `.\venv\Scripts\python.exe -m unittest tests.test_annotation_creation_factory tests.test_plan_view_action_handler tests.test_detached_window_workspace_state -v`
  passed: 136 tests.
- `.\venv\Scripts\python.exe tools\check_architecture.py --changed-only`
  passed.
- `git diff --check` passed with only pre-existing CRLF normalization warnings
  for unrelated dirty tracked files.
- `.\venv\Scripts\python.exe -m unittest discover -s tests -v` ran 984 tests
  with the two known unrelated tuple-vs-list failures in
  `tests/test_viewer_sync_coordinator_overlay_refresh.py`:
  `test_named_view_rename_uses_inline_edit_without_text_toolbar` and
  `test_selected_annotation_style_change_updates_only_selected_annotation`.

**Remaining tasks**

- Consider moving annotation default property generation out of presentation in
  a future phase only after raw MDB property-key ownership is clarified.

## Phase 6: ProjectDataService Reduction

**Status**

Complete for the first delegated behavior.

**Goal**

Gradually reduce `ProjectDataService` from an in-memory database facade into a
facade over richer domain helpers and aggregates.

**Files/areas affected**

- `ost_visualizer/domain/services/project_data_service.py`
- Domain entities, aggregates, and new helper modules.
- Application services/use cases that orchestrate mutations.
- Presentation handlers that currently rely on service mutation side effects.

**Exact type of changes**

- Identify one behavior with good tests, such as layer visibility, annotation
  style update, or condition layer ownership.
- Move that behavior into a domain helper or aggregate method.
- Leave `ProjectDataService` as the public facade and delegate to the new domain
  behavior.
- Avoid changing UI-facing method names in the same commit.
- Repeat for one behavior at a time.

**Risks**

- Service methods may have hidden UI refresh or persistence side effects.
- Moving mutation behavior can break bid lock, deferred persistence, or detached
  window synchronization if orchestration changes.
- Aggregates can become a second service layer if responsibilities are not
  narrow.

**Validation/tests needed**

- `tests.test_deferred_persistence_manager`
- Plan view action handler tests.
- Detached window workspace/state tests.
- Annotation, condition, and layer visibility tests affected by the behavior.
- Bid lock/write permission tests when mutation flow changes.
- `.\venv\Scripts\python.exe tools\check_architecture.py --changed-only`.
- `git diff --check`.

**Expected end state**

- `ProjectDataService` still shields UI/application code from churn, but key
  invariants begin to live in focused domain helpers or aggregates.
- Mutation behavior becomes easier to test without loading UI or MDB adapters.

**Rollback/compatibility notes**

- Because facade method names remain, each delegated behavior can be reverted
  independently.
- Do not remove service state until all consumers have moved to aggregate-backed
  flows.

**Completed work**

- Delegated Annotation-layer UID lookup and primary visibility resolution from
  `ProjectDataService` to the domain `LayerSet` helper.
- Kept `ProjectDataService.is_annotation_layer_visible()` and
  `ProjectDataService.get_annotation_layer_uid()` as the public facade methods
  used by presentation and application callers.
- Preserved the existing name-based visibility fallback for legacy in-memory
  states that have not populated layer UID/name maps.
- Added a regression test proving that when a layer UID exists, UID-keyed layer
  visibility is the source of truth over a stale name-keyed visibility entry.

**Decisions made**

- Use `LayerSet` for identity/visibility lookup only; leave layer mutation,
  condition-row updates, and page image visibility orchestration in
  `ProjectDataService` until they have a narrower aggregate/helper target.
- Prefer UID-keyed visibility when the Annotation layer UID is known because it
  matches the general layer-backed graphics model and avoids stale duplicate
  name visibility state.
- Keep the compatibility fallback for older tests or transient model states
  that only carry `bid_layer_visibility_by_name`.

**Files changed**

- `ost_visualizer/domain/services/project_data_service.py`
- `tests/test_deferred_persistence_project_state.py`
- `docs/architecture/mdb_domain_migration_plan.md`

**Validation results**

- `.\venv\Scripts\python.exe -m py_compile ost_visualizer\domain\services\project_data_service.py tests\test_deferred_persistence_project_state.py`
  passed.
- `.\venv\Scripts\python.exe -m unittest tests.test_deferred_persistence_project_state tests.test_domain_layers tests.test_annotation_creation_factory -v`
  passed: 15 tests.
- `.\venv\Scripts\python.exe tools\check_architecture.py --changed-only`
  passed.
- `git diff --check` passed with only CRLF normalization warnings for modified
  files.

**Remaining tasks**

- Delegate additional `ProjectDataService` behavior only when each behavior has
  focused tests and a clear domain helper target.
- Candidate future slices: condition layer ownership updates, page image-layer
  visibility updates, and annotation style mutation.

## Phase 7: Raw Export Boundary

**Goal**

Move raw OST/MDB export behavior behind an application/infrastructure boundary
so presentation no longer owns raw table ordering or schema details.

**Files/areas affected**

- `ost_visualizer/presentation/visualization/exporters/ost_exporter.py`
- Application export interfaces/services.
- Infrastructure MDB/export adapter code.
- Raw data DTOs such as `RawBidData`.
- Export tests and golden files.

**Exact type of changes**

- Add an application-level export port/service for OST-compatible export.
- Move raw table ordering and MDB/OST column lists into infrastructure or an
  export adapter module.
- Keep presentation responsible for user interaction and destination selection,
  not raw schema assembly.
- Preserve exact output order and values.
- Introduce a neutral wrapper such as `ExportSourceData` before relocating
  `RawBidData` if that lowers risk.

**Risks**

- Raw export may depend on exact column order and table order.
- Existing export tests may not cover all tables.
- Moving raw DTOs too early can create broad import churn.

**Validation/tests needed**

- Golden raw export tests before and after the move.
- Tests for old and newly created MDB export paths.
- `.\venv\Scripts\python.exe -m py_compile` on modified Python files.
- `.\venv\Scripts\python.exe tools\check_architecture.py --changed-only`.
- `git diff --check`.

**Expected end state**

- Presentation no longer imports MDB schema constants for export.
- Raw export remains MDB-compatible and byte/order-compatible where required.

**Rollback/compatibility notes**

- Keep old export implementation callable until the new service produces
  identical output.
- If output differs, rollback the adapter move and add a golden test for the
  uncovered case.

## What Not To Refactor Yet

- Do not remove MDB support or optional-schema compatibility.
- Do not rewrite all readers, writers, or schema creation logic in one PR.
- Do not remove `domain/ost_schema.py` until aliases have existed through the
  migration and all imports have moved.
- Do not eliminate `ProjectDataService` in one step.
- Do not change UID generation semantics without dedicated MDB compatibility
  tests.
- Do not move raw export DTOs before a replacement export boundary exists.
- Do not convert every dataclass into a rich entity at once.
- Do not change layer toggle performance characteristics or reintroduce broad
  condition/sidebar refreshes.
- Do not make presentation depend on infrastructure just to finish a migration
  step.

## First PR / First Commit Sequence

1. **Documentation/tests only**
   - Add this migration plan.
   - Add or list baseline MDB compatibility fixtures if the first migration PR
     needs missing coverage.
   - Run `git diff --check`.

2. **Move schema constants with compatibility aliases**
   - Add the infrastructure MDB schema contract.
   - Re-export existing names from `domain/ost_schema.py`.
   - Update infrastructure imports first.
   - Run py-compile, architecture check, MDB/schema tests, and `git diff --check`.

3. **Add neutral port aliases**
   - Add `ProjectReadPort`, `ProjectWritePort`, and
     `ProjectStorageConnectionPort`.
   - Keep `IMdbReader`, `IMdbWriter`, and `IMdbConnectionManager` as aliases or
     derived protocols.
   - Update one low-risk use case.

4. **Add the first mapper/factory around one narrow concept**
   - Prefer `MdbLayerMapper` if the goal is schema/default-layer safety.
   - Prefer `MdbAnnotationMapper` if the goal is to reduce reload-only repair.
   - Add direct mapper tests for partial rows.

5. **Align one part of `database_creator.py` with the shared contract**
   - Start with reserved/default layer definitions.
   - Add read-back tests for newly created MDBs.

6. **Add a domain helper for annotation layer identity**
   - Centralize annotation layer UID assignment and reserved layer lookup.
   - Keep existing placement handlers calling through their current service
     facade.

7. **Delegate one `ProjectDataService` behavior to a domain helper**
   - Choose layer visibility or annotation creation first.
   - Keep the public service API stable.

8. **Move raw export access behind a port**
   - Introduce the application export boundary.
   - Preserve exact raw output ordering with golden tests.

## Compatibility Notes

- Older MDB files can omit optional columns or tables; mapper boundaries must
  preserve current `MdbSchemaInspector` behavior.
- Annotation rows without `BidLayerUID` must still map to the reserved
  Annotation layer.
- Reserved layer roles currently depend on legacy names such as `Image`,
  `Annotation`, `Default`, and `Comments`; future role helpers must map those
  names without breaking existing files.
- UID generation often depends on current table values and Access-compatible
  assumptions; do not change it as part of boundary cleanup.
- Raw OST export may require exact table and column ordering; treat output
  ordering as compatibility behavior.
- Schema creator alignment must be validated against both new MDB creation and
  old MDB reading.

## Validation Checklist

For this documentation-only change:

```powershell
git diff --check
```

For later implementation phases that modify Python code:

```powershell
.\venv\Scripts\python.exe -m py_compile <modified Python files>
.\venv\Scripts\python.exe tools\check_architecture.py --changed-only
git diff --check
```

Add targeted tests for the phase being changed. Use the Phase 0 baseline when a
change touches MDB reader, writer, schema creator, layer identity, annotation
creation, or raw export behavior.
