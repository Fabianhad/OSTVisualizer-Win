# Second-pass test audit: handoff (written 2026-11-06, refreshed 2026-11-08 after waves 7 and 8)

The audit is **not finished**. This file says where it stands and where the next round starts. The numbers below were checked against `tests/quality_review.json` and `tests/quality_inventory.json` on 2026-11-08 (HEAD `50c0d98` plus the uncommitted wave-7 and wave-8 work: 14 production files, one new tool, one test helper and 65 test modules, 3 of them new); if the ledger and this file disagree, the ledger wins.

Source of truth: `tests/quality_review.json` -> `audit_2026-11-05_checkpoint` (per-module status in `modules`, `module_counts`, `owner_decisions_needed`, `production_changes`, and the sections `resolution_2026-11-06`, `wave3_2026-11-07` to `wave6_2026-11-07` and `wave8_2026-11-08`). `tests/quality_inventory.json` is regenerated with `tools/inventory_test_quality.py --discover` and matches the files on disk (600 modules, 18,923 defined tests, every sha256 current; `reconciliation_wave8_2026-11-08` lists what moved).

## The rule that governs the numbers

A module counts as second-passed **only** if its status is `Verified`: a verifier agent separate from the auditor re-inspected the diff, re-ran the tests, reproduced the mutation results and re-argued every survivor, and the module has not changed since. `Awaiting Verification`, `In Progress`, `Blocked`, `Partial` and `Verification Failed` are not second-passed. Never let an auditor approve its own work. The percentages below count every method of a Verified module (as the earlier waves did), including first-pass tests the second pass did not touch; per-test notes were not recorded for waves 7 and 8, so the inventory's per-method `second_pass_status` (6,501 reviewed) did not move and the module status is the authority.

## Where things stand (ledger `module_counts`, 167 tracked modules)

| Status | Modules | Before waves 7/8 |
| --- | --- | --- |
| Verified | 115 | 48 |
| Awaiting Verification | 5 | 60 |
| In Progress | 24 | 24 |
| Blocked | 18 | 18 |
| Partial | 2 | 1 |
| Verification Failed | 0 | 9 |
| Merged into another module | 3 | 3 |

Verified: **115 of 600 inventory modules (19.2 percent) and 6,542 of 18,923 tests (34.6 percent)**, against 48 of 597 modules (8.0 percent) and 2,235 of 17,965 tests (12.4 percent) at the start of wave 7. Four ledger entries are new (`test_cover_sheet`, `test_elevation_text`, `tests/helpers/test_import_workflow`, `tests/tools/test_check_stray_folders`).

- **Wave 7 (2026-11-07 to 11-08)**: independent verifiers re-ran the sweeps of the wave-3 to wave-6 modules. Every module of the earlier Awaiting Verification, Verification Failed and wave-4/5/6 lists that was in scope is now Verified (57 modules; the full list, with the modules of wave 8, is `wave8_2026-11-08.verified`), among them eight of the nine former Verification Failed modules (`ai_changeset_store`, `ai_takeoff_tokens`, `bridge_client`, `registry`, `main`, `output_artifacts`, `proxy`, `composite_renderer`); the ninth, `ai_takeoff_bridge`, was verified after its rework in wave 8.
- **Wave 8 (2026-11-08)**: fixers closed the verifier findings and the owner decisions with a failing test first (`production_changes.wave8_2026-11-08`: 14 production files, the new `tools/check_stray_folders.py`, the `FakeOspCab` guard); verifiers re-checked and approved every production change. Modules verified in wave 8 (most after rework): `test_database_maintenance`, `test_mdb_writer`, `sql/test_writer`, `test_database_creator`, `test_ai_takeoff_bridge`, `test_osp_importer`, `test_ost_importer`, `tests/helpers/test_import_workflow`, `test_import_operations`, `test_annotation_operations`, `domain/entities/test_layer`, `test_registry`, `test_overlay_rect`, `test_progress_dialog`, the three orchestrator modules and `tests/tools/test_check_stray_folders`.
- No module needed the "Awaiting Verification (wave-8 additions)" downgrade: every changed test file has a recorded verdict (checked against `git status` and the inventory sha256 values). Four modules differ in sha256 from the previous inventory with no test change (`test_uom_service`, `test_bid_data_reader`, `test_condition_folder_operations`, `test_project_operations`: formatting only).

### Open modules (7), left open by owner decision (reduced scope)

- **Partial, `infrastructure/mdb/test_connection_manager` (137 tests)**: widening the two eviction `close()` guards (`connection_manager` L213 and L239, `pyodbc.Error` -> `Exception`) survives; that is the owner-pending behaviour (a non-driver exception from `conn.close()` during eviction replaces an in-flight interrupt; data safe). Also unclassified, pre-existing and untouched: L78 (default argument), L110, L115 (keep operand 1) and L241 (const 0 -> -1). The production fix (wrapper, manager, SQL writer) is Approved.
- **Partial, `domain/services/test_ai_planar_regions` (246 tests)**: V1d round 2 found two real gaps, `_runs_along_an_edge` const 0.0 -> -1.0 (anti-parallel closing edge at unit scale) and `_VertexIndex._cell` const 1 -> 0 (low). `SmallScaleGapClosingTests` and `VertexIndexTieTests` were added afterwards to close them and have no independent verification. The tie rule (last vertex wins) is pinned by `PlanarTieRuleTests` and `VertexIndexTieTests`; AGENTS.md M2.3 now states the code's rule.
- **Awaiting Verification, `application/services/test_ai_takeoff_proposal_service` (297 tests)**: V2h round 2 was interim (stopped): the full sweep of the final file is clean (2,346 mutants, 2,272 killed, 65 survivors) but the operator, constant and default sweeps and the probes were not re-run, so four round-1 gaps are not mutation-confirmed killed (`_touches_box` y orientation, L437 text centre, L712 gap order, L1382 cap hint, plus L1614/L1615). Seven timeouts were argued, not re-run.
- **Awaiting Verification, `presentation/test_main_window` (343 tests)**: A3m only (2,825 mutants, 12 survivors argued equivalent); no verifier. Open question on the `bool()` coercion of four sidebar/status setters.
- **Awaiting Verification, `infrastructure/mdb/test_raw_bid_integrity` (118 tests)**: one real gap open, L408 keep operand 0 (a duplicate UID with a self-parent row plus a null-parent twin); the 3,868-mutant sweep was not re-run on the final file.
- **Awaiting Verification, `presentation/managers/test_deferred_persistence_manager` (216 tests, unchanged)**: A3l stopped early; the supplementary sweep (1,007 mutants) stopped at 300 with 40 survivors unanalysed, 121 hand mutants and the multi-seed sweep not run, four hang-only mutants have no assertion-based kill.
- **Awaiting Verification, `presentation/handlers/test_plan_view_action_handler` (590 tests, unchanged)**: A3n stopped early; 237 survivors in 67 functions are not classified (likely real gaps: warning text at L3486-3487, history keys and kind strings, error messages, `_execute_local_plan_properties` text/style branches, deepcopy deletions).

Other statuses are as in the earlier handoff: **Blocked (18)** (`bid_operations`, `condition_operations`, `settings_operations`, 11 native PDF integration modules, 3 PDF renderer modules, `ai_takeoff_pdf_source`), **In Progress (24)** (including `plan_view/test_view.py` with 1,085 tests, `page_operations`, `takeoff_operations`, `ost_exporter`, the corpus tool modules), and about 430 inventory modules with only the 2026-10-01 first-pass review (and some of the 2026-10 targeted second passes).

## Open owner questions (18, full text in `wave8_2026-11-08.owner_questions_open`)

1. Bridge worker-thread `SystemExit` (`_run_worker_job`): no `_job_finished`, no reply, the slot stays unreleased.
2. Bridge test-teardown deadlock hygiene (`handle.Close()` while a helper blocks in `ReadFile`; an additive `CancelIoEx` fix exists).
3. `overlay_units_per_sheet_inch` leaks `OverflowError` for huge scale factors.
4. `full_page_overlay_rect` with a `None` or non-numeric page dimension (pinned as a characterisation).
5. Maintenance work folder deleted after a successful rename-back (kept and pinned).
6. `MdbWriter` catches any `BaseException` (manager and SQL writer were aligned up, not narrowed).
7. `import_operations._convert_access_value`: `OverflowError` from an absurd datetime text propagates (characterisation).
8. Padded or float uids accepted by annotation position saves (characterisation).
9. Manager `conn.close()` non-driver error during eviction (decides `test_connection_manager`).
10. Orchestrators: unguarded non-blocking calls (`is_alive`, logger), a raising logger, an interrupt after the OS thread started.
11. Pre-existing: a failing `request_callback` leaves `_operation_in_progress` True.
12. A second Windows instance overwrites the bridge token file.
13. OSP names ending in a dot or space are now rejected.
14. OSP superscript device names and `CONIN$`/`CONOUT$` are rejected (the module's own table).
15. `Path.resolve()` maps a subst drive to its real folder (see "Running sweeps safely").
16. `check_stray_folders` state version 1: an older state is rejected.
17. `test_main_window`: the `bool()` coercion of the sidebar/status setters.
18. `deferred_persistence_manager` L698 mutants (unreachable only if a database never converts between SQL and MDB).

Decisions already taken (ledger `owner_decisions_taken`): the planar tie rule, OSP reserved names, the interrupt policy, a too-long configured path in `file_state.json` is ignored, the `test_layer` fixture change, the `None`-overlay `TypeError` in `render_composite_frame` left alone, and the test-hygiene rules below.

## Running sweeps safely (the stray-folder lesson)

All three folders that appeared under `C:\` (`T`, `outside`, `OSTVTemp`) were side effects of in-memory mutants of `osp_importer` exercised by `test_osp_importer` with the real working folder and TEMP and literal `C:\` fixtures; there is no production defect. An empty `C:\OSTVTemp` from 11-08 12:05 is still on the owner's disk (the stray tool does not fail on an old untouched copy). Rules (also in `AGENTS.md`, "Stray-folder check" and "Mutation sweeps and probes"):

1. Never run a sweep or a probe with the repository as working folder or with the real TEMP. Use a throw-away folder outside the repository and off `C:\` for the working folder and `TEMP`/`TMP`, with `PYTHONDONTWRITEBYTECODE=1` and `QT_QPA_PLATFORM=offscreen`. The audit used a shared runner kept outside the repository (the coordinator's scratch folder, `w7/runner/sandbox_run.py`; it is **not** in the repo, recreate it from these rules): it sets cwd and TEMP in a sandbox, maps the sandbox to a free drive letter with `subst` by default (`--no-subst` to disable), points `SystemDrive` at it, snapshots the top level of `C:\` and the number of `ostv_osp_*` folders in the real temp before and after and prints a STRAY report (exit 97).
2. Use the subst drive for the OSP importer sweeps. `Path.resolve()` maps a subst drive to its real folder, so path-equality tests can fail only under subst: the three OSP tests were rewritten to compare resolved paths; 13 tests of `tests/mcp_server/test_registry.py` fail under subst, so run `tests/mcp_server` with `--no-subst`.
3. Tests never use literal `C:\` names for hostile paths: derive them from the test's own folder with `hostile_cab_member_names(outside_dir, extract_root)`; `FakeOspCab` raises `AssertionError` instead of writing outside its output folder.
4. Before and after every full suite run or sweep: `python tools\check_stray_folders.py snapshot --state <file>` and `python tools\check_stray_folders.py compare --state <same file>` (the file outside the repo and outside any drive root; exit 1 = findings, exit 2 = tool error; one stderr warning past 20,000 entries).
5. A harness that imports the repo package must still chdir to a sandbox; `ost_visualizer/**/__pycache__` folders are git-ignored but must not be created by agents (`PYTHONDONTWRITEBYTECODE=1`).

## Where the next round starts

1. **Decide the owner questions** above; questions 9 (manager `close()` guards) and 17/18 unblock modules directly.
2. **Close the seven open modules**: have a verifier confirm the two planar killers (`SmallScaleGapClosingTests`, `VertexIndexTieTests`); pin or fix the manager eviction guards, then re-verify `test_connection_manager`; finish V2h for `test_ai_takeoff_proposal_service` (operator sweep of 277, constants 36, defaults 14, the probes, the four gaps); write the L408 test for `test_raw_bid_integrity` and verify; classify the 237 survivors of `test_plan_view_action_handler` and the 40 of `test_deferred_persistence_manager`, then verify both; verify `test_main_window`.
3. **Split the Blocked and large In Progress modules** (`bid_operations`, `settings_operations`, `condition_operations`, `page_operations`, `takeoff_operations`, `plan_view/test_view.py`) into several agents each; build `ost_pdf`/`ost_pdf_writer` before the PDF modules.
4. The AI modules never reached (`not_started.other` in the ledger) and the 15 PDF modules of `not_started.A6b`.
5. Commit the waves 7 and 8 (nothing is committed): run the full suite first (`QT_QPA_PLATFORM=offscreen .\venv\Scripts\python.exe -X faulthandler -m unittest discover -s tests -t .`, about 8 minutes) between the stray-tool snapshot and compare, compare with `wave3_2026-11-07.validation`, and regenerate the inventory.

## Production changes since the checkpoint

Recorded in the ledger under `production_changes` (`resolution_2026-11-06`, `wave3_2026-11-07` to `wave6_2026-11-07`, `wave8_2026-11-08`). The wave-8 changes were each proven by a failing test and approved by an independent verifier (V9a, V9b, V8c, V2f, V3h, V9c, V9d, V10); the earlier waves' fixes are approved only where the ledger names a verifier.

## Audit evidence not retained

`tests/_audit_progress/` (agent and verifier reports, per-test notes, survivor dispositions, killer-test drafts, harness copies), `tests/_audit_backup_2026-11-05/`, `_audit_snapshots/` and the `base_ai.json.cov` / `base_tk.json.cov` files no longer exist. The owner deleted them on 2026-11-06; none was ever in git and none is recoverable. Do not look for them. The reports of waves 7 and 8 lived in the coordinator's session scratch folder outside the repository and are likewise not part of the repository. The ledger keeps the conclusions it records (module statuses, mutation totals, remaining gaps, owner decisions and questions, the resolution sections). Modules that are not `Verified` must be re-audited, not resumed from reports.

## How to resume on another computer

1. `git pull` branch `main`. Create the venv and build the native extensions as described in `AGENTS.md` (the `.pyd` files are git-ignored and must be rebuilt per machine).
2. Work from the ledger only.
3. Run the suite and compare with `wave4_2026-11-07` / `wave3_2026-11-07.validation` in the ledger: `QT_QPA_PLATFORM=offscreen .\venv\Scripts\python.exe -X faulthandler -m unittest discover -s tests -t .` (about 8 minutes; 44 tests are skipped for environment reasons, plus one symlink test in `test_check_stray_folders` and the six `FullSizeSeededSegmentCapTests` without `OSTV_SLOW_TESTS`). Compare discovery with `.\venv\Scripts\python.exe tools\inventory_test_quality.py --discover --output <file>`.
4. New test files must mirror a production module (`tests.architecture.test_test_layout`; `tests/helpers/test_X.py` is allowed when `tests/helpers/X.py` exists); put scripts and scratch output outside the repository (`tests/` is not a scratch folder) and run Python with `PYTHONDONTWRITEBYTECODE=1`.
5. Tests that create Access databases do it in a child process (in-process creation exhausts DAO client tasks); gate them with `tests.helpers.mdb.schema_support._access_available()`.
6. Keep every ledger entry honest: set `Verified` only after separate-agent approval, merge verified per-test notes into the module entry at the end, regenerate the inventory, and keep both ledgers' CRLF line endings.
