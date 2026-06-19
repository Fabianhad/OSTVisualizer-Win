# MDB Boundary Architecture Report

## Summary

The current codebase is still materially shaped around the reverse engineered
OST `.mdb` schema. Compatibility with existing `.mdb` files is mandatory and
should remain, but the application and domain layers expose too many MDB-shaped
concepts: table names, column names, raw row containers, and MDB-specific ports.

The main issue is not that the MDB adapter exists. The issue is that the
persistence contract and the domain model are not clearly separated. Some
infrastructure readers do useful mapping and repair work, but raw MDB concepts
also appear in `domain`, `application`, and `presentation`, so the app model and
the persistence format are coupled in both directions.

## Current Architecture Map

### Domain

- `domain/entities/*` contains dataclasses such as `Condition`, `Takeoff`,
  `BidAnnotation`, `Page`, `BidPageInfo`, `BidLayer`, and hierarchy types.
- `domain/aggregates/ost_aggregate.py` stores current app state as public lists
  and dictionaries.
- `domain/services/project_data_service.py` acts as the main in-memory data
  access and mutation facade.
- Raw MDB table-section names previously lived in the domain layer. They now
  belong in the infrastructure MDB schema contract and should stay out of
  domain code.

### Application

- Use cases orchestrate actions but many are typed directly against
  `IMdbWriter`.
- `application/interfaces/i_mdb_reader.py`,
  `i_mdb_writer.py`, and `i_mdb_connection_manager.py` are persistence-specific
  ports in the application layer.
- Application DTOs such as `InsertAnnotationSpec` are mostly domain-oriented, but
  can carry MDB-derived property keys through generic dictionaries.

### Infrastructure/MDB

- `infrastructure/mdb/database_creator.py` is the concrete schema creator. It
  contains raw `CREATE TABLE` SQL, default layer rows, index lists, and foreign
  key relationships.
- `infrastructure/mdb/components/*` contains readers/writers for bid data,
  annotations, conditions, layers, pages, settings, and hierarchy.
- `schema_compatibility.py` adapts to older or partial schemas through optional
  table/column checks and SQL defaults.
- `MdbFileParser` in
  `infrastructure/persistence/repositories/file_project_repository.py` converts
  `MdbReader` tuples into `BidLoadResult`.

### UI/Presentation

- Most UI code consumes domain/application objects, but some export and
  annotation paths still know MDB details.
- The pre-migration raw OST exporter used raw table names, column names, and
  `RawBidData` directly from presentation. Raw OST serialization should remain
  behind the infrastructure/application export boundary.
- `presentation/utils/annotation_defaults.py` and some hotlink paths use keys
  such as `BidPageViewUID`, `BidTakeoffFromUID`, and `BidTakeoffToUID`.

### Schema Creator

- The creator is an independent SQL/table definition source.
- It does not appear to share a typed persistence contract with the readers and
  writers; alignment is maintained manually by parallel constants, SQL strings,
  table lists, and tests.

## MDB Leakage Examples

- The old domain-owned schema module defined `BidLayers`, `BidPages`,
  `BidTakeoffs`, `BidNamedViews`, `BidHotLinks`, and other raw table names.
  That made the domain layer aware of the MDB storage layout.
- `domain/dtos/raw_bid_data_dto.py` models `RawBidData` as raw table maps. That
  may be useful for export, but it is not a domain concept.
- `application/interfaces/i_mdb_writer.py` and `i_mdb_reader.py` expose MDB as
  the application port name. Use cases depend on `IMdbWriter`, not on a
  persistence-neutral project write port.
- The old presentation raw OST exporter consumed `RawBidData` and contained
  large MDB/OST column order lists.
- `presentation/utils/annotation_defaults.py` emits property dictionaries with
  MDB column names such as `BidPageViewUID` and `BidTakeoffFromUID`.
- `domain/entities/annotation.py` exposes `hotlink_target_view_uid` by reading
  `properties["BidPageViewUID"]`, so an MDB column key is part of domain entity
  behavior.

## Anemic Entity Examples

- `Condition` is mostly a row-shaped dataclass. It has type predicates but no
  invariant methods for layer membership, dimensional validity, quantity
  configuration, style updates, or placement rules.
- `BidLayer` is a storage-shaped dataclass with `show`, `is_template`, and
  `is_locked`; layer visibility/merge/default behavior lives in helper
  functions and services.
- `BidPageInfo` is an intermediate read model nearly identical to `Page`; both
  carry many of the same fields.
- `BidLoadResult` is a container for loaded tables/entities rather than a
  cohesive bid aggregate.
- `RawBidData` is intentionally raw, but it currently sits in `domain/dtos`.
- `Takeoff` has a few useful predicates, but position mutation, rotation
  mutation, text-style mutation, grouping, and reassign behavior live outside it.
- `BidAnnotation` has helpful geometry/type predicates, but its style/text
  mutations and some persistence-key properties live in services and UI code.

## Behavior Living Away From Entities/Aggregates

- `ProjectDataService` directly mutates `Condition.layer_visible`,
  `Page.layer_visible`, `Takeoff.position`, `Takeoff.rotation`, annotation
  positions, annotation style fields, and annotation text properties.
- `LoadBidUseCase` directly assigns `OstAggregate` collections after loading a
  bid instead of asking a bid aggregate to load/replace state.
- Layer visibility is split between `ProjectDataService`, sidebar coordinator
  logic, PlanView registration, page image visibility, and persistence writers.
- Annotation default layer assignment is now centralized enough for placement,
  but the rule still depends on service lookups rather than an explicit
  annotation factory.
- `annotation_operations.py` maps a single annotation concept across many MDB
  tables and expects generic `properties` dictionaries for table-specific
  columns.

## Duplicated Concepts And Models

- Page data exists as `BidPageInfo`, `Page`, hierarchy page info,
  `PageViewDto`, page rows in raw exports, and UI selection state.
- Layers exist as `Layer`, `BidLayer`, dictionaries in `OstAggregate`
  (`bid_layer_visibility`, `bid_layer_names_by_uid`,
  `bid_layer_visibility_by_name`), sidebar rows, and MDB `BidLayers`.
- Annotations exist as `BidAnnotation`, `InsertAnnotationSpec`, multiple MDB
  annotation tables, renderer item maps, and generic property dictionaries.
- Bid/project state exists in hierarchy DTOs, `Bid`, `BidLoadResult`,
  `OstAggregate`, file repository cache entries, and UI tree state.
- Raw table data exists as `RawBidData` in domain and is consumed by
  presentation export code.

## Repair And Defaulting Logic

These are necessary compatibility adaptations, but most should stay at explicit
MDB mapper/factory boundaries:

- `MdbSchemaInspector.optional_column(...)` and
  `optional_table_missing(...)` repair older schemas by supplying SQL defaults
  or skipping missing structures.
- `bid_data_reader._parse_bid_pages_for_bid(...)` derives page image-layer
  visibility from the reserved Image layer and supplies many default values for
  missing page columns.
- `bid_data_reader._parse_bid_conditions_for_bid(...)` supplies defaults for
  optional condition columns and derives `layer_visible` from `BidLayerUID`.
- `annotation_reader._parse_bid_annotations_for_bid(...)` maps many MDB
  annotation tables into one `BidAnnotation` type and assigns the default
  Annotation layer when a table has no `BidLayerUID` or a row layer is absent.
- `database_creator.py` defines default reserved layers (`Image`, `Annotation`,
  `Default`, `Comments`) independently from the reader and layer-domain helpers.
- Writer code often accepts partially domain-shaped objects plus raw property
  dictionaries, then decides which MDB columns to write.

## Diagnosis

The system is not cleanly hexagonal around the MDB store. It is closer to:

```text
UI and application use cases
        |
domain entities plus MDB-shaped DTOs
        |
MdbReader/MdbWriter plus schema compatibility
```

The architecture checker still enforces import direction, but the vocabulary
crosses boundaries. The domain and application layers know too much about the
storage adapter, and infrastructure sometimes has to compensate for domain
objects that are not rich enough to enforce invariants before persistence.

`ProjectDataService` is effectively an in-memory database facade. It is useful
as a transition seam, but it owns too many mutation rules and directly edits
records that could be protected by bid/page/layer/annotation aggregates.

## Recommended Target Architecture

Use MDB as one persistence adapter behind stable application ports:

```text
presentation
    -> application use cases and DTOs
        -> domain aggregates/entities/value objects
            <- application ports
                <- infrastructure/mdb adapter
```

Recommended boundaries:

- Domain model represents OST Visualizer concepts: bid, page, condition,
  takeoff, annotation, layer, view state, and page image/overlay state.
- Application ports use persistence-neutral names such as
  `ProjectReadPort`, `ProjectWritePort`, `BidRepository`,
  `AnnotationRepository`, or `LayerRepository`.
- MDB adapter translates tables, columns, optional schema quirks, and legacy
  repairs into domain objects at the boundary.
- Schema creator and reader/writer share one MDB persistence contract:
  table specs, column specs, defaults, reserved rows, and compatibility notes.
- Exporters that need raw OST/MDB output should live behind an export
  application service or infrastructure exporter, not presentation calling a raw
  MDB parser directly.
- Entities or small aggregates own core invariants: layer identity, annotation
  construction, takeoff reassignment/visibility rules, page overlay geometry,
  and layer reserved-role checks.

## Safe Migration Plan

1. Document the current MDB persistence contract.
   - Keep raw table-section names in an infrastructure MDB contract module.
   - Do not add alias-only modules or domain re-exports for migrated schema
     surfaces.

2. Introduce neutral application ports beside existing MDB ports.
   - Add interfaces such as `ProjectReadPort` and `ProjectWritePort`.
   - Let `MdbReader/MdbWriter` implement them.
   - Migrate use cases gradually from `IMdbWriter` naming to neutral ports.

3. Create explicit MDB mappers/factories.
   - `MdbBidMapper`, `MdbPageMapper`, `MdbLayerMapper`,
     `MdbAnnotationMapper`, `MdbTakeoffMapper`.
   - Keep optional-column defaults and row repairs inside these mappers.

4. Align schema creator with a single persistence contract.
   - Convert `database_creator.py` raw SQL lists into generated SQL from table
     specs or at least shared constants for tables, columns, reserved layers,
     indexes, and relationships.
   - Use the same contract in reader/writer/schema compatibility tests.

5. Extract domain-level factories for creation paths.
   - Example: `AnnotationFactory.create_placed(...)` assigns layer identity,
     style defaults, and property shape before persistence.
   - Example: `LayerSet` resolves reserved layers and visibility by UID/role.

6. Grow aggregates around existing data without big rewrites.
   - A `BidAggregate` can own conditions, layers, pages, takeoffs, annotations,
     and selected-page state.
   - `ProjectDataService` can become a facade over this aggregate instead of
     the place where mutation rules live.

7. Move raw export flow behind an application/infrastructure boundary.
   - Presentation asks for an OST export.
   - Export service obtains raw MDB-compatible data through a port or adapter.
   - Raw table ordering stays outside the UI layer.

8. Keep compatibility tests at the adapter boundary.
   - Golden legacy MDB fixtures and schema-variant tests should verify mapper
     behavior.
   - Domain tests should use domain objects and not raw table/column names.

## First Low-Risk Refactor Candidates

- Add narrow neutral ports directly when a use case migrates away from
  `IMdbWriter`/`IMdbReader`; do not add broad alias-only wrappers.
- Keep raw schema constants in `infrastructure/mdb/schema_contract.py` and keep
  MDB components/export adapters importing that contract directly.
- Move `RawBidData` from `domain/dtos` to an infrastructure/export boundary, or
  introduce a neutral `ExportSourceData` wrapper first.
- Add a `LayerSet` value object/factory to centralize reserved layer UID lookup,
  visibility, and merge behavior.
- Add annotation construction helpers that produce valid domain annotations or
  insert specs without raw MDB property names leaking to UI code.
- Consolidate creator/reader constants for default layers and layer-reference
  tables.

## Things Not To Refactor Yet

- Do not remove MDB compatibility or stop accepting optional/missing columns.
- Do not rewrite all readers/writers at once.
- Do not change UID generation semantics without fixture tests.
- Do not move PDF/OST export raw table ordering until a replacement export port
  exists.
- Do not turn every dataclass into a rich entity immediately; start with
  invariants that are already causing bugs, such as layer identity and
  annotation creation.
- Do not eliminate `ProjectDataService` in one step. It is a useful transition
  facade for UI/application code.

## Compatibility Risks

- Existing MDB files may omit columns that the current reader defaults through
  `MdbSchemaInspector`; mappers must preserve that behavior exactly.
- Some annotation types have no `BidLayerUID` table column and are Annotation
  layer-backed by convention; this must remain explicit in the mapper.
- Reserved layers are currently recognized by name (`Image`, `Annotation`,
  `Default`, `Comments`). A future role-based model must still map legacy names.
- UID generation currently often uses table `MAX([UID]) + 1`; changing that can
  break compatibility with Access autonumber expectations or copy/import flows.
- Raw OST export may require exact table/attribute order; moving it must preserve
  generated output.
- Schema creator changes can affect generated databases even if existing DB
  reading still works, so creator tests need to compare expected table/column
  contracts.

## Architectural Direction

The safest path is incremental: define an MDB persistence contract and neutral
ports first, then move repairs/defaulting into mapper classes, then grow richer
domain factories/aggregates around the invariants that are already painful. This
lets the app remain compatible with reverse engineered MDB files while gradually
making MDB a persistence adapter instead of the shape of the whole application.
