"""集中管理單位與研究參數；內部時間一律為整數 ps，距離為 mm。"""

import math
from dataclasses import asdict, dataclass

C_MM_PER_PS = 0.299792458
POSITION_COLUMNS = ["x_mm", "y_mm", "z_mm"]
TRUTH_COLUMNS = ["truth_source_x_mm", "truth_source_y_mm", "truth_source_z_mm"]


@dataclass(frozen=True)
class SimulationConfig:
    seed: int = 20261019
    n_events: int = 8000
    radius_mm: float = 400.0
    n_rings: int = 7
    detectors_per_ring: int = 48
    ring_pitch_mm: float = 30.0
    source_mm: tuple[float, float, float] = (20.0, -12.0, 12.0)
    activity_bq: float = 2_000_000.0
    detection_efficiency: float = 0.95
    timing_sigma_ps: float = 80.0
    energy_sigma_kev: float = 25.0
    background_singles: int = 700
    n_lanes: int = 14
    max_lane_delay_ps: int = 8000
    arrival_jitter_ps: int = 1000
    hemisphere_offset_ps: int = 0

    def __post_init__(self):
        positive = (
            "n_events",
            "radius_mm",
            "n_rings",
            "detectors_per_ring",
            "ring_pitch_mm",
            "activity_bq",
            "n_lanes",
        )
        for name in positive:
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} 必須為正值")
        for name in (
            "n_events",
            "n_rings",
            "detectors_per_ring",
            "background_singles",
            "n_lanes",
            "max_lane_delay_ps",
            "arrival_jitter_ps",
            "hemisphere_offset_ps",
        ):
            if not isinstance(getattr(self, name), int):
                raise ValueError(f"{name} 必須為整數")
        for name in (
            "timing_sigma_ps",
            "energy_sigma_kev",
            "background_singles",
            "max_lane_delay_ps",
            "arrival_jitter_ps",
        ):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f"{name} 不可為負值")
        if not 0 < self.detection_efficiency <= 1:
            raise ValueError("detection_efficiency 必須介於 (0, 1]")
        if len(self.source_mm) != 3 or not all(math.isfinite(v) for v in self.source_mm):
            raise ValueError("source_mm 必須包含三個有限座標")
        x, y, z = self.source_mm
        if math.hypot(x, y) >= self.radius_mm:
            raise ValueError("放射源必須位於偵測器圓筒內")
        if abs(z) >= self.n_rings * self.ring_pitch_mm / 2:
            raise ValueError("放射源必須位於有效軸向視野內")

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class CoincidenceConfig:
    window_ps: int = 4000  # 定義為最大 |t2-t1|，而非全寬的一半。
    energy_min_kev: float = 350.0
    energy_max_kev: float = 650.0
    min_angle_deg: float = 120.0

    def __post_init__(self):
        if not isinstance(self.window_ps, int) or not 0 <= self.window_ps <= 2**63 - 1:
            raise ValueError("window_ps 必須為 int64 範圍內的非負整數")
        if not (0 <= self.energy_min_kev < self.energy_max_kev < math.inf):
            raise ValueError("能量範圍無效")
        if not 0 <= self.min_angle_deg <= 180:
            raise ValueError("min_angle_deg 必須介於 0 與 180")
