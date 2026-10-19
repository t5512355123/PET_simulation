"""產生具有可追溯真值的理想化 PET singles 串流。"""

import numpy as np
import pandas as pd

from .config import C_MM_PER_PS, SimulationConfig


def _accepted_intersections(config: SimulationConfig, rng: np.random.Generator):
    """以各向同性方向取樣，條件為兩光子皆擊中圓筒有效軸向範圍。"""
    source = np.asarray(config.source_mm, dtype=float)
    half_length = config.n_rings * config.ring_pitch_mm / 2
    positions_1, positions_2, distances_1, distances_2 = [], [], [], []
    remaining = config.n_events
    radial_margin = config.radius_mm**2 - np.dot(source[:2], source[:2])
    while remaining:
        # 額外取樣可減少短軸向視野下的迴圈次數；拒絕取樣保留原來的角度分布。
        count = max(1024, remaining * 4)
        direction = rng.normal(size=(count, 3))
        direction /= np.linalg.norm(direction, axis=1)[:, None]
        a = np.sum(direction[:, :2] ** 2, axis=1)
        b = direction[:, :2] @ source[:2]
        root = np.sqrt(b**2 + a * radial_margin)
        forward = (-b + root) / a
        backward = (-b - root) / a
        p1 = source + forward[:, None] * direction
        p2 = source + backward[:, None] * direction
        accepted = (np.abs(p1[:, 2]) <= half_length) & (np.abs(p2[:, 2]) <= half_length)
        indices = np.flatnonzero(accepted)[:remaining]
        positions_1.append(p1[indices])
        positions_2.append(p2[indices])
        distances_1.append(forward[indices])
        distances_2.append(-backward[indices])
        remaining -= len(indices)
    return (
        np.concatenate(positions_1),
        np.concatenate(positions_2),
        np.concatenate(distances_1),
        np.concatenate(distances_2),
    )


def _detector_ids(positions: np.ndarray, config: SimulationConfig) -> np.ndarray:
    """只將識別碼量化；保留連續交點供幾何與 TOF 公式驗證。"""
    half_length = config.n_rings * config.ring_pitch_mm / 2
    ring = np.floor((positions[:, 2] + half_length) / config.ring_pitch_mm).astype(np.int64)
    ring = np.clip(ring, 0, config.n_rings - 1)
    angle = np.mod(np.arctan2(positions[:, 1], positions[:, 0]), 2 * np.pi)
    sector = np.floor(angle * config.detectors_per_ring / (2 * np.pi)).astype(np.int64)
    return ring * config.detectors_per_ring + sector


def simulate_singles(config: SimulationConfig) -> pd.DataFrame:
    """模擬 singles；n_events 為幾何接受後、效率篩選前的湮滅事件數。

    activity_bq 在此定義為幾何接受事件率，不能用於預測絕對靈敏度。
    此模型沒有散射、衰減、非共線性、晶體深度或真實晶體位置量化。
    光子能量使用高斯響應並將負值設為 0 keV（左側設限高斯）；背景為獨立時間、圓筒位置與
    100–800 keV 均勻能量。背景真值事件編號為 -1，源座標為 NaN。
    每個通道群具有固定隨機延遲，並加上非負均勻到達抖動。
    """
    int64_max = np.iinfo(np.int64).max
    if not -(2**63) <= config.hemisphere_offset_ps <= int64_max:
        raise ValueError("半環時間偏移超出 int64 ps 範圍")
    if max(config.max_lane_delay_ps, config.arrival_jitter_ps) > int64_max:
        raise ValueError("傳輸延遲設定超出 int64 ps 範圍")
    rng = np.random.default_rng(config.seed)
    p1, p2, d1, d2 = _accepted_intersections(config, rng)
    positions = np.stack((p1, p2), axis=1).reshape(-1, 3)
    distances = np.column_stack((d1, d2)).reshape(-1)
    interval_scale_ps = 1e12 / config.activity_bq
    if not np.isfinite(interval_scale_ps):
        raise ValueError("活動率過低，事件時間間隔超出可表示範圍")
    with np.errstate(over="ignore"):
        emission_ps = np.cumsum(rng.exponential(interval_scale_ps, config.n_events))
    if not np.isfinite(emission_ps).all() or np.any(emission_ps >= 2**63):
        raise ValueError("事件時間超出 int64 ps 範圍，請提高活動率或減少事件數")
    event_ids = np.repeat(np.arange(config.n_events, dtype=np.int64), 2)
    timestamps = (
        np.repeat(emission_ps, 2)
        + distances / C_MM_PER_PS
        + rng.normal(0, config.timing_sigma_ps, 2 * config.n_events)
        + (positions[:, 0] >= 0) * config.hemisphere_offset_ps
    )
    energies = np.maximum(rng.normal(511.0, config.energy_sigma_kev, 2 * config.n_events), 0.0)
    detected = rng.random(2 * config.n_events) < config.detection_efficiency
    positions, timestamps, energies, event_ids = (
        positions[detected],
        timestamps[detected],
        energies[detected],
        event_ids[detected],
    )
    truth_sources = np.repeat(
        np.asarray(config.source_mm, dtype=float)[None, :], len(event_ids), axis=0
    )

    if config.background_singles:
        count = config.background_singles
        phi = rng.uniform(0, 2 * np.pi, count)
        half_length = config.n_rings * config.ring_pitch_mm / 2
        background_positions = np.column_stack(
            (
                config.radius_mm * np.cos(phi),
                config.radius_mm * np.sin(phi),
                rng.uniform(-half_length, half_length, count),
            )
        )
        # 背景時間是獨立偵測事件時間，不對應任何湮滅源或成對光子。
        background_times = rng.uniform(0, emission_ps[-1], count)
        background_times += (background_positions[:, 0] >= 0) * config.hemisphere_offset_ps
        positions = np.concatenate((positions, background_positions))
        timestamps = np.concatenate((timestamps, background_times))
        energies = np.concatenate((energies, rng.uniform(100, 800, count)))
        event_ids = np.concatenate((event_ids, np.full(count, -1, dtype=np.int64)))
        truth_sources = np.concatenate((truth_sources, np.full((count, 3), np.nan)))

    # timestamp 是偵測器量測時間；arrival_time 另外加入傳輸延遲，兩者不可混用。
    rounded_times = np.rint(timestamps)
    # 上界採 2**63 的開區間，避免 float64 將 int64 最大值捨入成 2**63。
    if (
        not np.isfinite(rounded_times).all()
        or np.any(rounded_times < -(2**63))
        or np.any(rounded_times >= 2**63)
    ):
        raise ValueError("偵測時間超出 int64 ps 範圍")
    timestamps = rounded_times.astype(np.int64)
    detectors = _detector_ids(positions, config)
    lanes = detectors % config.n_lanes
    lane_delays = rng.integers(0, config.max_lane_delay_ps + 1, config.n_lanes)
    jitter = rng.integers(0, config.arrival_jitter_ps + 1, len(timestamps))
    delays = lane_delays[lanes]
    if np.any(delays > int64_max - jitter):
        raise ValueError("抵達時間延遲總和超出 int64 ps 範圍")
    offsets = delays + jitter
    if np.any(timestamps > int64_max - offsets):
        raise ValueError("抵達時間超出 int64 ps 範圍")
    arrival_times = timestamps + offsets
    frame = pd.DataFrame(
        {
            "single_id": np.arange(len(timestamps), dtype=np.int64),
            "timestamp_ps": timestamps,
            "detector_id": detectors,
            "x_mm": positions[:, 0],
            "y_mm": positions[:, 1],
            "z_mm": positions[:, 2],
            "energy_kev": energies,
            "arrival_time_ps": arrival_times,
            "lane_id": lanes,
            "truth_event_id": event_ids,
            "truth_source_x_mm": truth_sources[:, 0],
            "truth_source_y_mm": truth_sources[:, 1],
            "truth_source_z_mm": truth_sources[:, 2],
        }
    )
    return frame.sort_values("arrival_time_ps", kind="stable").reset_index(drop=True)
