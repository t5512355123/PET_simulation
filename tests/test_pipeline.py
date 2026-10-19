"""驗證完整輸出、體素計數與無符合事件時的可用性。"""

import json

import numpy as np

from pet_sim.config import SimulationConfig
from pet_sim.pipeline import run_pipeline
from pet_sim.simulation import simulate_singles
from pet_sim.validation import validate_software


def test_end_to_end_artifacts(tmp_path):
    cfg = SimulationConfig(n_events=120, background_singles=10)
    frame = simulate_singles(cfg)
    metrics = run_pipeline(frame, tmp_path, dataset_kind="synthetic", source_mm=cfg.source_mm,
                           simulation_config=cfg)
    assert metrics["true_pairs"] > 80
    volume = np.load(tmp_path / "ror_volume.npz")
    assert volume["counts"].shape == (64, 64, 64)
    assert volume["counts"].sum() == metrics["histogram_counts_inside_100mm_cube"]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert "metrics.json" in manifest["sha256"]
    assert (tmp_path / "ror_projections.png").stat().st_size > 1000


def test_empty_pipeline(tmp_path):
    frame = simulate_singles(SimulationConfig(n_events=1, background_singles=0)).head(0)
    metrics = run_pipeline(frame, tmp_path)
    assert metrics["coincidence_pairs"] == 0
    assert metrics["all_valid_centroid_mm"] is None


def test_independent_software_validation():
    assert validate_software()["passed"]
