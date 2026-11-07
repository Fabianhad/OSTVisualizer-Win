# Second-pass test audit: WIP handoff (2026-11-06)

> **Update (2026-11-07).** The audit evidence folder `tests/_audit_progress/` was not retained (deleted 2026-11-06, never committed, not recoverable); do not look for it. The owner decisions listed below were decided on 2026-11-06 and implemented; the outcomes are in the ledger section `resolution_2026-11-06`. The counts and lists below describe the checkpoint, not the current state: use the ledger.

This is a checkpoint, **not** a finished audit. The owner switched computers while many agents were running; every agent was stopped at its own safe checkpoint.

Source of truth for status: `tests/quality_review.json` -> `audit_2026-11-05_checkpoint` (per-module status, production changes, owner decisions, suite result). `tests/quality_inventory.json` is regenerated and matches the filesystem.

## The rule that governs the numbers
A module counts as second-passed **only** if its status is `Verified`, meaning a verifier agent separate from the auditor re-inspected the diff, re-ran the tests, reproduced the mutation results and re-argued every survivor. `Awaiting Verification`, `In Progress`, `Blocked`, `Partial` and `Verification Failed` are not second-passed.

Roles: auditors A1..A7 (+A4b, A5b, A6b) wrote tests and swept mutants; verifiers V1..V7 re-checked. Mapping is in the ledger section `agents`.

## Where things stand (from the ledger)
- Verified (54 entries): A1's SQL modules (5), A2's file operation handler and project write service, A3's page combo / UI event coordinator / window, A4's pipe client / tool catalog / server / internal server (+11 AI/MCP modules verified on the first pass and **not re-run** after A4's rework; A4 says it did not touch them), A5's serialization and ost_serializer, A6's PDF modules (9), A7's 17 domain/application modules.
- Awaiting Verification (53 entries): reworked modules after a failed verification (deferred persistence manager, main window, layer_operations, bid_data_reader, overlay_rect, identity_allocation, ...) and A5b's 21 MDB modules, A7's ten re-noted modules.
- Verification Failed: `test_composite_renderer.py` (V6 found 22 more killable survivors; the scratch killers were not retained).
- Partial: `test_ai_takeoff_proposal_service.py` (14 genuine gaps left, 5 more mutants killable).
- In Progress (27) and Blocked (23): A3's `plan_view/test_view.py`, A4b's corpus and corpus-worker modules (about 657 of 689 worker mutants unmeasured against the final tests), A5b's four modules, A7's remaining modules, A5's eight blocked modules.
- Never started: A6b (15 PDF modules), plus AI modules A4 never reached (see `not_started`).

## Production changes in the checkpoint
| File | Origin | Status |
|---|---|---|
| `composite_renderer.py` | A6, one line | V6 verified |
| `page_combo.py` | A3 `_on_model_data_changed` + the owner's own IDE edits | V3 verified A3's part |
| `ui_event_coordinator.py` | owner's IDE edit (three comments removed) | not an agent change |
| `mdb/connection_manager.py` | A5b sub-worker g4a | justified (regression test fails on HEAD) per V5; **not independently approved**: its test module is Awaiting Verification |

## Decisions that belong to the owner (nothing implemented)
OPEN-1 annotation preflight scope, OPEN-2 schema validator scope, the curved-linear `area_sf` defect, the arc-orientation heuristic, and the AGENTS.md documentation proposed by A4. Details and evidence are in the ledger section `owner_decisions_needed`. For OPEN-2, no validator restriction may be added without an explicit product decision.

## Audit evidence not retained
`tests/_audit_progress/` (agent and verifier reports, per-test notes, survivor dispositions, killer-test drafts and harness copies), `tests/_audit_backup_2026-11-05/`, `_audit_snapshots/` and the `base_ai.json.cov` / `base_tk.json.cov` files no longer exist. The owner deleted them on 2026-11-06; none of them was ever in git and none is recoverable. The ledger keeps the conclusions it already records (module statuses, owner decisions, the resolution section and the per-test notes inside module entries). The detailed per-test notes, survivor lists and killer drafts for the modules that are not yet `Verified` are lost, so those modules must be re-audited, not resumed from reports. Verifier outcomes from the second wave that were never consolidated into the ledger are lost as well (see `resolution_2026-11-06.module_status_note`).

## How to resume on another computer
1. `git pull` the checkpoint commit(s) on branch `main`. Create the venv and build native extensions as in `AGENTS.md`.
2. Work from the ledger section only: the evidence folder `tests/_audit_progress/` was not retained and must not be expected.
3. Run the suite: `QT_QPA_PLATFORM=offscreen .\venv\Scripts\python.exe -X faulthandler -m unittest discover -s tests -t .` and compare with `full_suite` in the ledger section. Run `.\venv\Scripts\python.exe tools\inventory_test_quality.py --discover --output <file>` to compare discovery.
4. Resume in this order: (a) verify the Awaiting Verification modules (fresh verifier agents; never let an auditor approve its own work); (b) finish the In Progress / Blocked modules (A5b's four, A4b's worker sweep, A3's `test_view.py`, A7's remainder, A5's eight); (c) rework `test_composite_renderer.py` and the proposal service (the earlier scratch killers were not retained; write new ones); (d) run A6b's 15 PDF modules; (e) the AI modules never reached; (f) decide OPEN-1/OPEN-2 and the other owner decisions.
5. New test files must mirror a production module (`tests.architecture.test_test_layout`); put scripts outside `tests/`.
6. Keep every ledger entry honest: set `Verified` only after separate-agent approval, and merge verified per-test notes into `quality_review.json` module entries at the end.
