"""以獨立配對 oracle 與解析解進行端到端驗證及同步誤差實驗。"""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from .coincidence import brute_force_pair_ids, find_coincidences
from .config import C_MM_PER_PS, CoincidenceConfig, SimulationConfig
from .metrics import summarize
from .reconstruction import reconstruct_ror
from .simulation import simulate_singles


def pair_ids(frame):
    return {
        tuple(sorted((int(a), int(b))))
        for a, b in frame[["single_id_1", "single_id_2"]].itertuples(index=False, name=None)
    }


def validate_software():
    settings = CoincidenceConfig()
    base = SimulationConfig(n_events=1000)
    singles = simulate_singles(base)
    subset = singles.sort_values("timestamp_ps").head(600)
    oracle = brute_force_pair_ids(subset, settings)
    found = pair_ids(find_coincidences(subset, settings))
    assert oracle == found, "滑動視窗與獨立暴力比對不一致"
    shuffled = subset.sample(frac=1, random_state=5)
    assert pair_ids(find_coincidences(shuffled, settings)) == found, "輸入順序影響配對"
    ideal = simulate_singles(
        replace(
            base,
            detection_efficiency=1.0,
            timing_sigma_ps=0,
            energy_sigma_kev=0,
            background_singles=0,
            activity_bq=10_000,
        )
    )
    ror = reconstruct_ror(find_coincidences(ideal, settings))
    truth = ror.loc[ror.same_truth_event]
    errors = np.linalg.norm(
        truth[["ror_x_mm", "ror_y_mm", "ror_z_mm"]].to_numpy() - np.asarray(base.source_mm), axis=1
    )
    # 整數 ps 量化在每端最多 0.5 ps，位移最大約 c/2 ps = 0.15 mm。
    assert len(truth) == base.n_events
    assert errors.max() <= C_MM_PER_PS / 2 + 1e-5
    noisy_config = replace(
        base, n_events=12000, background_singles=0, detection_efficiency=1.0, activity_bq=10_000
    )
    noisy = reconstruct_ror(find_coincidences(simulate_singles(noisy_config), settings))
    true_noisy = noisy.loc[noisy.same_truth_event]
    xyz = true_noisy[["ror_x_mm", "ror_y_mm", "ror_z_mm"]].to_numpy()
    rmse = float(np.sqrt(np.mean(np.sum((xyz - np.asarray(base.source_mm)) ** 2, axis=1))))
    expected = C_MM_PER_PS * base.timing_sigma_ps / np.sqrt(2)
    assert abs(rmse / expected - 1) < 0.05
    return {
        "passed": True,
        "oracle_singles": len(subset),
        "oracle_pairs": len(oracle),
        "oracle_matches_sliding_window": True,
        "arrival_order_invariant": True,
        "noiseless_true_pairs": len(truth),
        "noiseless_max_error_mm": float(errors.max()),
        "integer_ps_error_bound_mm": C_MM_PER_PS / 2,
        "timing_rmse_mm": rmse,
        "timing_expected_rmse_mm": float(expected),
        "timing_relative_error": abs(rmse / expected - 1),
    }


def run_sweep(output_path):
    rows = []
    base = SimulationConfig(
        n_events=4000, background_singles=0, detection_efficiency=1.0, activity_bq=10_000
    )
    for sigma in (0, 40, 80, 160):
        for bias in (0, 100, 300):
            cfg = replace(base, timing_sigma_ps=sigma, hemisphere_offset_ps=bias)
            singles = simulate_singles(cfg)
            ror = reconstruct_ror(find_coincidences(singles))
            metrics = summarize(singles, ror, "synthetic", cfg.source_mm)
            rows.append(
                {
                    "timing_sigma_ps": sigma,
                    "hemisphere_offset_ps": bias,
                    "true_pairs": metrics["true_pairs"],
                    "centroid_error_mm": metrics["truth_centroid_error_mm"],
                    "event_rmse_mm": metrics["truth_event_rmse_mm"],
                    "expected_timing_rmse_mm": C_MM_PER_PS * sigma / np.sqrt(2),
                }
            )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(out, index=False)
    return frame
