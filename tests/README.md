# Test layout

Primary tests mirror `ost_visualizer/`: for example,
`presentation/handlers/condition_action_handler.py` maps to
`tests/presentation/handlers/test_condition_action_handler.py`.
The same rule applies to repository tools and `sql_server/python/ostv_sql_admin`.
Classes within larger primary modules group tests by the production method;
same-file fixture bases contain shared setup, not duplicate tests.

Run discovery with the repository as the top-level directory:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -t . -v
.\venv\Scripts\python.exe -m unittest discover -s tests/presentation -t . -v
.\venv\Scripts\python.exe -m unittest tests.presentation.handlers.test_condition_action_handler
```

`-t .` is important: it keeps `tests.tools` distinct from the repository's
production `tools` namespace and gives fixtures one canonical import identity.

## Broader subjects

`integration/` retains workflows whose assertions cross real component
boundaries: persistence/reconstruction, MDB/SQL parity, history, multiple Qt
surfaces, native rendering, and import/export roundtrips. A Qt widget test is
not automatically an integration test; tests focused on one widget or mixin
stay with that source module. `architecture/` contains source/build contract
checks. `helpers/sql/test_*.py` tests the safety contracts of the SQL test
harness itself. `helpers/sql/strict_sql_fakes.py` is the strict pyodbc/T-SQL
stand-in for the SQL infrastructure tests (marker/parameter counts, the
2100-parameter limit, closed cursors, session `SET NOCOUNT` rowcounts, result
sets and the busy connection, autocommit-only DDL, transaction-owned
application locks, snapshot isolation rules and the canonical v1 catalog);
prefer it, or `strict_manager`/`strict_cursor` around an existing canned fake,
over a permissive per-test cursor. Its contract is pinned in
`tests/infrastructure/sql/test_connection_manager.py`. It is a model, not SQL
Server: it proves protocol rules, never T-SQL correctness. Opt-in extras:
`model_result_counts` (a batch that leaves `SET NOCOUNT` OFF fronts its rows
with count-only result sets) and `helpers/sql/sqlite_lock_validation.py`, which
runs the SQL the SQL writer really sent (lock validation and operation prepare)
on sqlite against described lock/session/version rows with an injected server
clock; sqlite is not T-SQL, so those tests prove predicate logic only.

Fixtures live beside the contract they implement. Shared workspace and SQL
fixtures remain in `helpers/`; rendering, permissions, window lifetime, and
dialog fixtures have narrower subsystem owners. Prefer importing a fixture
directly instead of importing another test class. Some established test-class
factories remain available to preserve existing workflow behavior.

## Coverage map

`layout_inventory.json` inventories production classes, methods, private
helpers, explicit failure/lifecycle paths, primary-test locations, and test
imports/calls. Regenerate it with:

```powershell
.\venv\Scripts\python.exe tools/inventory_test_layout.py --output tests/layout_inventory.json --prefix no_such_test
```

The static map is supplemented by `execution_inventory.json`, a snapshot of
Python function calls during the migration's full-suite run. It records the
test count and outcome. Discovery/import-time execution is excluded. Child
processes and native Qt worker threads are not comprehensively observed.
This is **not** statement or branch coverage: an import does not prove execution,
and a call does not prove every branch. Class declarations naturally have no
matching function-call entry. The snapshot describes its recorded run, not
future edits. Regenerating the static map alone does not rerun call observation.

Entries without primary tests distinguish interface/data contracts, constants,
thin delegation, integration/neighbor references, observed indirect calls, and
reviewed operational entry points. Every production source has its proposed
primary path and symbol inventory even when there is no isolated test. The
remaining direct-coverage exceptions are intentional, not empty test shells:

- Main-window Hotlink and icon-provider adapters delegate to separately tested
  behavior without their own stateful test subject.
- SQL environment auditing/provisioning are operator tools; this migration does
  not change server configuration or credentials to exercise them.
- The architecture checker is run directly in full and changed-only modes.
- Cover Sheet profiling is an environment-dependent manual timing harness.

The file-association CLI has dedicated argument/default-path and failure tests
with the registrar replaced at its boundary; no registry changes are made.

Per-source reasons and the complete list of modules without primary tests live
in `source_to_tests` in the JSON map. An integration reference is not a claim of
complete coverage. Unobserved methods remain visible for future targeted work.
New direct unit coverage belongs at the listed primary path; cross-system
coverage belongs in the appropriate integration category.

Architecture tests enforce mirrored primary paths, importable discovery, and
the absence of legacy flat-test imports. The migration inventory checker can
compare original method/assertion counts with a chosen Git baseline; additions
are reported separately and never substitute for removed assertions.
