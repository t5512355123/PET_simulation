"""檢驗可獨立推導的 TOF 公式、幾何真值與統計關係。"""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from pet_sim.config import C_MM_PER_PS, SimulationConfig
from pet_sim.reconstruction import histogram_ror, reconstruct_ror
from pet_sim.simulation import simulate_singles


def _truth_pairs(singles):
    """僅供單元測試，使用真值建立成對輸入以隔離符合器的影響。"""
    ordered = singles.sort_values(["truth_event_id", "single_id"])
    first, second = ordered.iloc[::2], ordered.iloc[1::2]
    return pd.DataFrame(
        {
            "x1_mm": first.x_mm.to_numpy(),
            "y1_mm": first.y_mm.to_numpy(),
            "z1_mm": first.z_mm.to_numpy(),
            "t1_ps": first.timestamp_ps.to_numpy(),
            "x2_mm": second.x_mm.to_numpy(),
            "y2_mm": second.y_mm.to_numpy(),
            "z2_mm": second.z_mm.to_numpy(),
            "t2_ps": second.timestamp_ps.to_numpy(),
        }
    )


def test_tof_sign_and_swap_invariance():
    # 源位於 x=30 mm，靠近右端；右端應先到，dt 為負。
    pair = pd.DataFrame(
        {
            "x1_mm": [-400.0],
            "y1_mm": [0.0],
            "z1_mm": [0.0],
            "x2_mm": [400.0],
            "y2_mm": [0.0],
            "z2_mm": [0.0],
            "t1_ps": [430 / C_MM_PER_PS],
            "t2_ps": [370 / C_MM_PER_PS],
        }
    )
    result = reconstruct_ror(pair)
    assert result.ror_x_mm.iloc[0] == pytest.approx(30.0)
    swapped = pair.rename(
        columns={
            "x1_mm": "x2_mm",
            "y1_mm": "y2_mm",
            "z1_mm": "z2_mm",
            "t1_ps": "t2_ps",
            "x2_mm": "x1_mm",
            "y2_mm": "y1_mm",
            "z2_mm": "z1_mm",
            "t2_ps": "t1_ps",
        }
    )
    np.testing.assert_allclose(
        reconstruct_ror(swapped)[["ror_x_mm", "ror_y_mm", "ror_z_mm"]],
        result[["ror_x_mm", "ror_y_mm", "ror_z_mm"]],
        atol=1e-12,
    )


def test_noiseless_simulation_reconstructs_source_with_integer_ps_bound():
    config = SimulationConfig(
        n_events=1500,
        detection_efficiency=1,
        timing_sigma_ps=0,
        energy_sigma_kev=0,
        background_singles=0,
    )
    singles = simulate_singles(config)
    assert len(singles) == 2 * config.n_events
    np.testing.assert_allclose(np.hypot(singles.x_mm, singles.y_mm), config.radius_mm, atol=1e-10)
    assert singles.z_mm.abs().max() <= config.n_rings * config.ring_pitch_mm / 2
    result = reconstruct_ror(_truth_pairs(singles))
    errors = np.linalg.norm(
        result[["ror_x_mm", "ror_y_mm", "ror_z_mm"]].to_numpy() - config.source_mm,
        axis=1,
    )
    # 兩端各自四捨五入至整數 ps，時間差誤差至多 1 ps。
    assert errors.max() <= C_MM_PER_PS / 2 + 1e-7
    assert result.physical_tof_valid.all()


def test_simulation_is_deterministic_and_background_has_no_source_truth():
    config = SimulationConfig(n_events=200, background_singles=30)
    first = simulate_singles(config)
    pd.testing.assert_frame_equal(first, simulate_singles(config))
    assert not first.equals(simulate_singles(replace(config, seed=config.seed + 1)))
    assert first.single_id.is_unique
    assert first.timestamp_ps.dtype == np.int64
    assert first.arrival_time_ps.is_monotonic_increasing
    assert (first.arrival_time_ps >= first.timestamp_ps).all()
    assert (first.truth_event_id == -1).sum() == config.background_singles
    assert (
        first.loc[
            first.truth_event_id == -1,
            [
                "truth_source_x_mm",
                "truth_source_y_mm",
                "truth_source_z_mm",
            ],
        ]
        .isna()
        .all()
        .all()
    )


def test_longitudinal_variance_matches_independent_single_timing_noise():
    config = SimulationConfig(
        n_events=25000,
        detection_efficiency=1,
        background_singles=0,
        timing_sigma_ps=80.0,
        max_lane_delay_ps=0,
        arrival_jitter_ps=0,
    )
    pairs = _truth_pairs(simulate_singles(config))
    result = reconstruct_ror(pairs)
    vector = (
        pairs[["x2_mm", "y2_mm", "z2_mm"]].to_numpy()
        - pairs[["x1_mm", "y1_mm", "z1_mm"]].to_numpy()
    )
    unit = vector / np.linalg.norm(vector, axis=1)[:, None]
    errors = result[["ror_x_mm", "ror_y_mm", "ror_z_mm"]].to_numpy() - config.source_mm
    longitudinal = np.sum(errors * unit, axis=1)
    predicted_sigma = C_MM_PER_PS * config.timing_sigma_ps / np.sqrt(2)
    assert np.std(longitudinal, ddof=1) == pytest.approx(predicted_sigma, rel=0.025)


def test_impossible_tof_is_flagged_without_clipping_and_histogram_conserves_counts():
    pair = pd.DataFrame(
        {
            "x1_mm": [-10],
            "y1_mm": [0],
            "z1_mm": [0],
            "x2_mm": [10],
            "y2_mm": [0],
            "z2_mm": [0],
            "t1_ps": [0],
            "t2_ps": [1000],
        }
    )
    result = reconstruct_ror(pair)
    assert not result.physical_tof_valid.iloc[0]
    assert result.ror_x_mm.iloc[0] < -10
    volume, edges = histogram_ror(result, bins=10, extent_mm=200)
    assert volume.shape == (10, 10, 10)
    assert volume.sum() == 1
    assert len(edges) == 3
    with pytest.raises(ValueError, match="兩端位置"):
        reconstruct_ror(pair.assign(x1_mm=10))


def test_empty_reconstruction_is_well_formed():
    empty = pd.DataFrame(
        columns=["x1_mm", "y1_mm", "z1_mm", "x2_mm", "y2_mm", "z2_mm", "t1_ps", "t2_ps"]
    )
    result = reconstruct_ror(empty)
    assert result.empty
    volume, _ = histogram_ror(result, bins=4)
    assert volume.sum() == 0


def test_integer_time_difference_preserves_ps_and_does_not_overflow():
    limits = np.iinfo(np.int64)
    pair = pd.DataFrame(
        {
            "x1_mm": [-400, -400],
            "y1_mm": [0, 0],
            "z1_mm": [0, 0],
            "x2_mm": [400, 400],
            "y2_mm": [0, 0],
            "z2_mm": [0, 0],
            "t1_ps": [10**18, limits.min],
            "t2_ps": [10**18 + 5, limits.max],
        }
    )
    result = reconstruct_ror(pair)
    assert result.tof_displacement_mm.iloc[0] == pytest.approx(-C_MM_PER_PS * 5 / 2)
    expected_difference = int(limits.max) - int(limits.min)
    assert result.tof_displacement_mm.iloc[1] == pytest.approx(
        -C_MM_PER_PS * expected_difference / 2
    )
    assert not result.physical_tof_valid.iloc[1]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"activity_bq": 1e-20},
        {"hemisphere_offset_ps": 2**63},
    ],
)
def test_simulation_rejects_unrepresentable_timestamps(kwargs):
    config = SimulationConfig(n_events=20, background_singles=0, detection_efficiency=1, **kwargs)
    with pytest.raises(ValueError, match="int64"):
        simulate_singles(config)


def test_simulation_rejects_arrival_time_overflow():
    config = SimulationConfig(
        n_events=100,
        background_singles=0,
        detection_efficiency=1,
        activity_bq=1e12,
        timing_sigma_ps=0,
        arrival_jitter_ps=0,
        hemisphere_offset_ps=2**63 - 1_000_000,
        max_lane_delay_ps=2_000_000,
    )
    with pytest.raises(ValueError, match="抵達時間"):
        simulate_singles(config)


def test_broad_energy_response_is_nonnegative_and_reproducible():
    config = SimulationConfig(
        n_events=1000, background_singles=0, detection_efficiency=1, energy_sigma_kev=500
    )
    singles = simulate_singles(config)
    assert (singles.energy_kev >= 0).all()
    assert (singles.energy_kev == 0).any()
    pd.testing.assert_frame_equal(singles, simulate_singles(config))
