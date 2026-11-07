# Second-pass test audit: handoff (written 2026-11-06, refreshed 2026-11-07 after wave 6)

The audit is **not finished**. This file says where it stands and where the next round starts. The numbers below were checked against `tests/quality_review.json` and `tests/quality_inventory.json` on 2026-11-07 (HEAD `5fe1ac2` plus the uncommitted wave-5 and wave-6 work); if the ledger and this file disagree, the ledger wins.

Source of truth: `tests/quality_review.json` -> `audit_2026-11-05_checkpoint` (per-module status in `modules`, `module_counts`, `owner_decisions_needed`, `production_changes`, and the sections `resolution_2026-11-06`, `wave3_2026-11-07`, `wave4_2026-11-07`, `wave5_2026-11-07`, `wave6_2026-11-07`). `tests/quality_inventory.json` is regenerated with `tools/inventory_test_quality.py --discover` and matches the files on disk (597 modules, 17,965 defined tests, every sha256 current).

## The rule that governs the numbers

A module counts as second-passed **only** if its status is `Verified`: a verifier agent separate from the auditor re-inspected the diff, re-ran the tests, reproduced the mutation results and re-argued every survivor, and the module has not changed since. `Awaiting Verification`, `In Progress`, `Blocked`, `Partial` and `Verification Failed` are not second-passed. Untouched first-pass tests inside a module are never counted as second-passed. Never let an auditor approve its own work.

## Where things stand (ledger `module_counts`, 163 tracked modules)

| Status | Modules |
| --- | --- |
| Verified | 48 |
| Awaiting Verification | 60 |
| In Progress | 24 |
| Blocked | 18 |
| Verification Failed | 9 |
| Partial | 1 |
| Merged into another module | 3 |

- **Awaiting Verification (wave-5 additions), 2 modules:** `test_layer_operations` (delete of locked built-in default layers) and `presentation/coordinators/test_ui_event_coordinator` (SQL lock read fails closed). They were Verified; their entries carry `status_before_wave5` and `wave5_2026-11-07`. Five more modules got wave-5 changes while already not Verified (`test_position_parser`, `test_settings_reader`, `test_bid_data_reader`, `test_settings_operations`, `test_collaboration_dtos`) and `test_schema_validator` got comment changes only.
- **Awaiting Verification (wave-6 additions), 1 module:** `domain/entities/test_layer` (the built-in default layer rule behind the Layers dialog). It was Verified; its entry carries `status_before_wave6` and `wave6_2026-11-07`. Wave 6 also changed tests in `test_layer_operations`, `test_settings_reader` and `test_ui_event_coordinator` (already Awaiting) and in two modules the ledger does not track (`presentation/dialogs/test_layers_dialog`, `application/services/test_project_read_service`).
- **Awaiting Verification (wave-4 additions), 7 modules:** `test_project_operations`, `sql/test_writer`, `test_settings_reader`, `test_progress_dialog`, `test_position_parser`, `test_ai_planar_regions`, `test_bid_data_reader`. They were Verified in wave 3; the wave-4 and wave-5 work added or re-baselined tests that no verifier has seen. Their entries carry `status_before_wave4` and `wave4_2026-11-07`.
- **Verification Failed (9):** `test_composite_renderer` (22 more killable survivors) and eight AI/MCP modules downgraded by VAI (`ai_changeset_store`, `ai_takeoff_tokens`, `bridge_client`, `registry`, `main`, `output_artifacts`, `proxy`, `ai_takeoff_bridge`).
- **Partial (1):** `test_ai_takeoff_proposal_service` (14 genuine gaps left, 5 more mutants killable).
- **Blocked (18):** `bid_operations`, `condition_operations`, `settings_operations` (too large for one agent), 11 native PDF integration modules and 3 PDF renderer modules plus `ai_takeoff_pdf_source` (need the native extensions built and licensed PDFs).
- **In Progress (24):** including `plan_view/test_view.py` (1,085 tests), `page_operations`, `takeoff_operations`, `ost_exporter`, the corpus tool modules, and smaller domain/DTO modules.
- The other ~434 inventory modules have only the 2026-10-01 first-pass review (one pass per test) and some of the 2026-10 targeted second passes (`second_pass_campaign`).

## Where the next round starts

1. **Verify the wave-4 and wave-5 modules (9 distinct modules)** with fresh verifier agents (cheapest, highest value: they were Verified one commit ago). Re-run the mutation sweeps from the ledger notes; the harness idea is an in-memory `__code__` swap per mutant in a child process (nothing written to the repo).
2. **Rework the 9 Verification Failed modules and the Partial one** (the earlier scratch killers were not retained; write new ones), then verify them.
3. **Verify the 50 other Awaiting Verification modules** (small DTO/orchestrator/MDB modules first).
4. **Split the Blocked and large In Progress modules** (`bid_operations`, `settings_operations`, `condition_operations`, `page_operations`, `takeoff_operations`, `plan_view/test_view.py`) into several agents each; build `ost_pdf`/`ost_pdf_writer` before the PDF modules.
5. The AI modules never reached (`not_started.other` in the ledger) and the 15 PDF modules of `not_started.A6b`.
6. Decide the open owner questions listed in the ledger (`owner_decisions_needed`, `wave3_2026-11-07.owner_decisions_or_observations`, `wave4_2026-11-07.items`). Resolved so far: OPEN-1 (option A), OPEN-2 (document only), curved `area_sf` (document only), the arc rule (mod 2 pi, applied), `perp_slope`, the `|` identity rule, the Deleted Bids writer guard, the fail-closed lock read, the planar order independence, `ProgressDialog._worker`, the detached minus in `position_parser`.

## Production changes since the checkpoint

Recorded in the ledger under `production_changes` (`resolution_2026-11-06`, `wave3_2026-11-07`, `wave4_2026-11-07`, `wave5_2026-11-07`, `wave6_2026-11-07`). None of them was approved by a verifier except those the ledger names; the wave-4 fixes were proven by failing tests and mutation-checked by their author only.

## Audit evidence not retained

`tests/_audit_progress/` (agent and verifier reports, per-test notes, survivor dispositions, killer-test drafts, harness copies), `tests/_audit_backup_2026-11-05/`, `_audit_snapshots/` and the `base_ai.json.cov` / `base_tk.json.cov` files no longer exist. The owner deleted them on 2026-11-06; none was ever in git and none is recoverable. Do not look for them. The ledger keeps the conclusions it records (module statuses, owner decisions, the resolution sections, per-test notes inside module entries). Verifier outcomes of the second wave that were never consolidated into `modules` are lost (`resolution_2026-11-06.module_status_note`), so modules that are not `Verified` must be re-audited, not resumed from reports.

## How to resume on another computer

1. `git pull` branch `main`. Create the venv and build the native extensions as described in `AGENTS.md` (the `.pyd` files are git-ignored and must be rebuilt per machine).
2. Work from the ledger only.
3. Run the suite and compare with `wave4_2026-11-07` / `wave3_2026-11-07.validation` in the ledger: `QT_QPA_PLATFORM=offscreen .\venv\Scripts\python.exe -X faulthandler -m unittest discover -s tests -t .` (about 8 minutes; 44 tests are skipped for environment reasons). Compare discovery with `.\venv\Scripts\python.exe tools\inventory_test_quality.py --discover --output <file>`.
4. New test files must mirror a production module (`tests.architecture.test_test_layout`); put scripts and scratch output outside the repository (`tests/` is not a scratch folder) and run Python with `PYTHONDONTWRITEBYTECODE=1`.
5. Tests that create Access databases do it in a child process (in-process creation exhausts DAO client tasks); gate them with `tests.helpers.mdb.schema_support._access_available()`.
6. Keep every ledger entry honest: set `Verified` only after separate-agent approval, merge verified per-test notes into the module entry at the end, regenerate the inventory, and keep both ledgers' CRLF line endings.
