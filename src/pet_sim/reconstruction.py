"""以兩端偵測位置與 TOF 差進行事件層級 ROR 定位與體素累積。"""

import numpy as np
import pandas as pd

from .config import C_MM_PER_PS


def reconstruct_ror(pairs: pd.DataFrame) -> pd.DataFrame:
    """計算 ROR 中心；不裁切超出 LOR 線段的非物理 TOF 估計。

    定義 u=(r2-r1)/L、dt=t2-t1，位置為 (r1+r2)/2-c*dt*u/2。
    此事件層級定位不是經過散射／衰減校正的臨床影像重建。
    """
    columns_1 = ["x1_mm", "y1_mm", "z1_mm"]
    columns_2 = ["x2_mm", "y2_mm", "z2_mm"]
    required = columns_1 + columns_2 + ["t1_ps", "t2_ps"]
    missing = [column for column in required if column not in pairs]
    if missing:
        raise ValueError(f"符合事件缺少必要欄位：{missing}")
    p1 = pairs[columns_1].to_numpy(dtype=float)
    p2 = pairs[columns_2].to_numpy(dtype=float)
    if not np.isfinite(p1).all() or not np.isfinite(p2).all():
        raise ValueError("偵測器座標必須為有限數值")
    times_1 = pd.to_numeric(pairs["t1_ps"], errors="raise").to_numpy()
    times_2 = pd.to_numeric(pairs["t2_ps"], errors="raise").to_numpy()
    if not np.isfinite(times_1).all() or not np.isfinite(times_2).all():
        raise ValueError("偵測時間必須為有限數值")
    # Python 整數不溢位；先做差再轉浮點也保留大絕對時間下的 ps 差值解析度。
    if np.issubdtype(times_1.dtype, np.integer) and np.issubdtype(times_2.dtype, np.integer):
        dt = np.fromiter(
            (int(t2) - int(t1) for t1, t2 in zip(times_1, times_2, strict=True)),
            dtype=float,
            count=len(pairs),
        )
    else:
        dt = times_2.astype(float) - times_1.astype(float)
    vector = p2 - p1
    length = np.linalg.norm(vector, axis=1)
    if np.any(length <= 0):
        raise ValueError("LOR 兩端位置不可相同")
    displacement = -C_MM_PER_PS * dt / 2
    point = (p1 + p2) / 2 + displacement[:, None] * vector / length[:, None]
    result = pairs.copy()
    result[["ror_x_mm", "ror_y_mm", "ror_z_mm"]] = point
    result["lor_length_mm"] = length
    result["tof_displacement_mm"] = displacement
    result["physical_tof_valid"] = np.abs(C_MM_PER_PS * dt) <= length
    return result


def histogram_ror(ror: pd.DataFrame, bins: int = 64, extent_mm: float = 100):
    """將 ROR 中心累積至立方體；範圍外點不計入，軸順序為 x、y、z。

    不依 physical_tof_valid 自動篩選；呼叫者可明確選取所需的事件。
    回傳計數陣列及三個軸的邊界，單位為 mm。
    """
    if not isinstance(bins, (int, np.integer)) or isinstance(bins, bool) or bins <= 0:
        raise ValueError("bins 必須為正整數")
    if not np.isfinite(extent_mm) or extent_mm <= 0:
        raise ValueError("extent_mm 必須為有限正值")
    points = ror[["ror_x_mm", "ror_y_mm", "ror_z_mm"]].to_numpy(dtype=float)
    if not np.isfinite(points).all():
        raise ValueError("ROR 座標必須為有限數值")
    volume, edges = np.histogramdd(
        points,
        bins=bins,
        range=[(-extent_mm, extent_mm)] * 3,
    )
    return volume, edges
