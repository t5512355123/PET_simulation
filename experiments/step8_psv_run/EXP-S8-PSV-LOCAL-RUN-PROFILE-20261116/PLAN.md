# EXP-S8-PSV-LOCAL-RUN-PROFILE-20261116 — PLAN

## Goal

Run the PETRIC2 winner (Speedy `psv`, SyneRBI/PETRIC2-Speedy commit 3cb1173) on a PETRIC2 dataset.
Show data loading, computation and result, and the share of time spent in each step.

## Setup

- Data: PETRIC2 test set NeuroLF_Esser2 (`D:\PET_DATA\petric2\NeuroLF_Esser2`).
- Hardware: local RTX 3070 Ti Laptop. Per the user's instruction, trader3, .26 and .171 are not used.
- Software: STIR 6.5 conda-forge CUDA build (parallelproj, CudaRelativeDifferencePrior), plus cupy 14.2 installed into the local `stir` env.
- SIRF is not available on Windows. A thin sirf.STIR / CIL compatible layer (`source/shim`) maps the SIRF calls onto STIR.
  - Team `main.py` and `rdp.py` run unmodified (SHA-256 in `source/team_code_sha256.txt`).
  - Metric formulas are copied from `petric.py`.

## Measurements

1. Per-update time and per-step self-time (exclusive section timers in the shim); metrics after every update, excluded from timing.
2. One subset gradient decomposed with the same STIR objects (`decompose_subgrad.py`).
3. Toy example with the same formulas (`toy.py`), used in the report.

## Pass criterion

Official PETRIC2 thresholds, held for 10 consecutive updates.
