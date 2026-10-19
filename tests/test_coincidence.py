"""測試時間窗端點、複數符合、整數精度與獨立暴力參考。"""

import numpy as np
import pandas as pd
import pytest

from pet_sim.coincidence import brute_force_pair_ids, find_coincidences, validate_singles
from pet_sim.config import CoincidenceConfig
from pet_sim.validation import pair_ids


def make_frame(times, angles=None, energies=None, ids=None):
    n = len(times)
    angle = np.deg2rad(angles if angles is not None else np.arange(n) * 180)
    return pd.DataFrame(
        {
            "single_id": np.arange(n, dtype=np.int64),
            "timestamp_ps": np.asarray(times, dtype=np.int64),
            "detector_id": ids if ids is not None else np.arange(n),
            "x_mm": 400 * np.cos(angle),
            "y_mm": 400 * np.sin(angle),
            "z_mm": 0.0,
            "energy_kev": energies if energies is not None else np.full(n, 511.0),
        }
    )


def test_inclusive_time_energy_and_angle_edges():
    frame = make_frame([0, 4000, 4001], [0, 120, 180], [350, 650, 511])
    pairs = pair_ids(find_coincidences(frame))
    assert pairs == {(0, 1)}


def test_all_pairs_multiples_and_equal_times():
    frame = make_frame([9, 9, 9], [0, 120, 240])
    assert pair_ids(find_coincidences(frame)) == {(0, 1), (0, 2), (1, 2)}
    assert len(find_coincidences(frame, CoincidenceConfig(window_ps=0))) == 3


def test_detector_and_energy_filter():
    assert find_coincidences(make_frame([0, 1], ids=[3, 3])).empty
    assert find_coincidences(make_frame([0, 1], energies=[349.9, 511])).empty


def test_no_float_precision_or_int64_overflow_in_matcher():
    base = 2**60
    assert len(find_coincidences(make_frame([base, base + 1]), CoincidenceConfig(window_ps=1))) == 1
    edge = np.iinfo(np.int64)
    assert find_coincidences(make_frame([edge.min, edge.max])).empty


@pytest.mark.parametrize("seed", range(12))
def test_randomized_oracle_and_arrival_permutation(seed):
    rng = np.random.default_rng(seed)
    n = 50
    frame = make_frame(
        rng.integers(0, 20000, n),
        rng.uniform(0, 360, n),
        rng.uniform(250, 750, n),
        rng.integers(0, 20, n),
    )
    cfg = CoincidenceConfig(window_ps=1700)
    reference = brute_force_pair_ids(frame, cfg)
    assert pair_ids(find_coincidences(frame, cfg)) == reference
    assert pair_ids(find_coincidences(frame.sample(frac=1, random_state=seed), cfg)) == reference


def test_truth_is_not_used_for_pairing_and_runs_scope_labels():
    frame = make_frame([0, 1])
    before = pair_ids(find_coincidences(frame))
    frame["truth_event_id"] = [1, 1]
    frame["truth_run_id"] = [0, 1]
    after = find_coincidences(frame)
    assert before == pair_ids(after)
    assert not after.same_truth_event.any()


def test_empty_and_bad_inputs():
    assert find_coincidences(make_frame([])).empty
    frame = make_frame([0, 1])
    frame.loc[1, "single_id"] = 0
    with pytest.raises(ValueError, match="single_id"):
        validate_singles(frame)
    with pytest.raises(ValueError, match="缺少"):
        validate_singles(pd.DataFrame())
    frame = make_frame([0, 1])
    frame["timestamp_ps"] = [0.0, 1.0]
    with pytest.raises(ValueError, match="整數"):
        validate_singles(frame)
    frame = make_frame([0, 1])
    frame.loc[0, "energy_kev"] = np.nan
    with pytest.raises(ValueError, match="有限"):
        validate_singles(frame)


@pytest.mark.parametrize(
    "kwargs",
    [{"window_ps": -1}, {"min_angle_deg": 181}, {"energy_min_kev": 700}, {"window_ps": 2**63}],
)
def test_invalid_cuts(kwargs):
    with pytest.raises(ValueError):
        CoincidenceConfig(**kwargs)
