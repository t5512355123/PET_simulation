"""離線全配對參考實作；不利用 truth 或傳輸抵達順序決定配對。"""

import math

import numpy as np
import pandas as pd

from .config import POSITION_COLUMNS, TRUTH_COLUMNS, CoincidenceConfig

REQUIRED_COLUMNS = ["single_id", "timestamp_ps", "detector_id", *POSITION_COLUMNS, "energy_kev"]
PAIR_COLUMNS = [
    "single_id_1",
    "single_id_2",
    "t1_ps",
    "t2_ps",
    "dt_ps",
    "detector_id_1",
    "detector_id_2",
    "energy1_kev",
    "energy2_kev",
    "x1_mm",
    "y1_mm",
    "z1_mm",
    "x2_mm",
    "y2_mm",
    "z2_mm",
]


def validate_singles(singles: pd.DataFrame) -> pd.DataFrame:
    """檢查明確的統一欄位，拒絕缺值、浮點時間戳與重複 single ID。"""
    missing = set(REQUIRED_COLUMNS) - set(singles.columns)
    if missing:
        raise ValueError(f"Singles 缺少欄位：{sorted(missing)}")
    frame = singles.copy()
    for col in ("single_id", "timestamp_ps", "detector_id"):
        if len(frame) and not pd.api.types.is_integer_dtype(frame[col]):
            raise ValueError(f"{col} 必須使用整數，請先明確轉換單位")
        if len(frame) and (
            frame[col].min() < np.iinfo(np.int64).min or frame[col].max() > np.iinfo(np.int64).max
        ):
            raise ValueError(f"{col} 超出 int64")
        frame[col] = frame[col].astype("int64")
    if frame.single_id.duplicated().any():
        raise ValueError("single_id 不可重複")
    for col in [*POSITION_COLUMNS, "energy_kev"]:
        frame[col] = pd.to_numeric(frame[col], errors="raise").astype(float)
        if not np.isfinite(frame[col]).all():
            raise ValueError(f"{col} 必須為有限數值")
    if (frame.energy_kev < 0).any():
        raise ValueError("energy_kev 不可為負值")
    if ((frame.x_mm == 0) & (frame.y_mm == 0)).any():
        raise ValueError("偵測器橫向位置不可位於原點，無法定義環向角度")
    return frame


def _geometry_good(a, b, config):
    if a.detector_id == b.detector_id:
        return False
    dot = a.x_mm * b.x_mm + a.y_mm * b.y_mm
    cross = abs(a.x_mm * b.y_mm - a.y_mm * b.x_mm)
    angle = math.degrees(math.atan2(cross, dot))
    return angle + 1e-10 >= config.min_angle_deg


def find_coincidences(
    singles: pd.DataFrame, config: CoincidenceConfig | None = None
) -> pd.DataFrame:
    """依時間排序後滑動視窗，全列出合格的無序 pair；一個 single 可出現多次。

    能量與時間邊界均包含端點；幾何為橫向環向角差。時間複雜度為
    O(N log N + K)，K 是時間窗內候選對數；密集輸入最壞仍為 O(N²)。
    """
    config = config if config is not None else CoincidenceConfig()
    frame = validate_singles(singles)
    frame = frame.loc[frame.energy_kev.between(config.energy_min_kev, config.energy_max_kev)]
    frame = frame.sort_values(["timestamp_ps", "single_id"], kind="stable")
    rows = list(frame.itertuples(index=False))
    output = []
    has_truth = "truth_event_id" in frame
    has_run = "truth_run_id" in frame
    has_source = all(c in frame for c in TRUTH_COLUMNS)
    for i, a in enumerate(rows):
        j = i + 1
        while j < len(rows):
            b = rows[j]
            # 使用 Python int 做差，避免 int64 極值相減溢位。
            dt = int(b.timestamp_ps) - int(a.timestamp_ps)
            if dt > config.window_ps:
                break
            if _geometry_good(a, b, config):
                pair = dict(
                    zip(
                        PAIR_COLUMNS,
                        [
                            a.single_id,
                            b.single_id,
                            a.timestamp_ps,
                            b.timestamp_ps,
                            dt,
                            a.detector_id,
                            b.detector_id,
                            a.energy_kev,
                            b.energy_kev,
                            a.x_mm,
                            a.y_mm,
                            a.z_mm,
                            b.x_mm,
                            b.y_mm,
                            b.z_mm,
                        ],
                        strict=True,
                    )
                )
                if has_truth:
                    pair["truth_event_id_1"] = a.truth_event_id
                    pair["truth_event_id_2"] = b.truth_event_id
                    pair["same_truth_event"] = bool(
                        a.truth_event_id >= 0
                        and a.truth_event_id == b.truth_event_id
                        and (not has_run or a.truth_run_id == b.truth_run_id)
                    )
                if has_source:
                    for col in TRUTH_COLUMNS:
                        pair[col] = getattr(a, col)
                output.append(pair)
            j += 1
    columns = PAIR_COLUMNS.copy()
    if has_truth:
        columns += ["truth_event_id_1", "truth_event_id_2", "same_truth_event"]
    if has_source:
        columns += TRUTH_COLUMNS
    result = pd.DataFrame(output, columns=columns)
    # 空輸出也保留可供後續重建與序列化的固定型態。
    for col in [
        "single_id_1",
        "single_id_2",
        "t1_ps",
        "t2_ps",
        "dt_ps",
        "detector_id_1",
        "detector_id_2",
    ]:
        result[col] = result[col].astype("int64")
    if has_truth:
        result["same_truth_event"] = result.same_truth_event.astype(bool)
    return result


def brute_force_pair_ids(singles: pd.DataFrame, config: CoincidenceConfig) -> set:
    """獨立 O(N²) oracle：不排序、不共用主演算法的幾何判斷函式。"""
    frame = validate_singles(singles)
    records = frame.to_dict("records")
    answer = set()
    for i in range(len(records)):
        a = records[i]
        for j in range(i + 1, len(records)):
            b = records[j]
            if a["detector_id"] == b["detector_id"]:
                continue
            if not all(
                config.energy_min_kev <= r["energy_kev"] <= config.energy_max_kev for r in (a, b)
            ):
                continue
            if abs(int(a["timestamp_ps"]) - int(b["timestamp_ps"])) > config.window_ps:
                continue
            delta = abs(math.atan2(a["y_mm"], a["x_mm"]) - math.atan2(b["y_mm"], b["x_mm"]))
            angle = math.degrees(min(delta, 2 * math.pi - delta))
            if angle + 1e-10 >= config.min_angle_deg:
                answer.add(tuple(sorted((a["single_id"], b["single_id"]))))
    return answer
