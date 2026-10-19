"""分開統計資料流、truth 同事件關係與 ROR 定位誤差。"""

import numpy as np


def summarize(singles, ror, dataset_kind="imported", source_mm=None):
    metrics = {
        "dataset_kind": dataset_kind,
        "singles": len(singles),
        "coincidence_pairs": len(ror),
        "physical_tof_valid_pairs": int(ror.physical_tof_valid.sum()),
        "pair_policy": "all_pairs; inclusive |dt| <= window_ps; transaxial angle",
    }
    if "arrival_time_ps" in singles:
        order = singles.sort_values(["arrival_time_ps", "single_id"])
        times = order.timestamp_ps.tolist()
        metrics["adjacent_timestamp_inversions"] = sum(
            int(times[i]) < int(times[i-1]) for i in range(1, len(times)))
    if "same_truth_event" in ror:
        mask = ror.same_truth_event.astype(bool)
        metrics["same_truth_event_pairs"] = int(mask.sum())
        metrics["same_truth_event_fraction"] = float(mask.mean()) if len(mask) else None
        if dataset_kind == "synthetic":
            metrics["true_pairs"] = int(mask.sum())
            metrics["false_pairs"] = int((~mask).sum())
            # 模擬每個 event 至多兩個 singles，故此處可計算雙端可觀測事件 recall。
            ids = singles.loc[singles.truth_event_id >= 0].groupby("truth_event_id").size()
            complete = int((ids == 2).sum())
            metrics["two_detected_photon_events_before_cuts"] = complete
            metrics["recall_before_energy_time_geometry_cuts"] = (
                int(mask.sum()) / complete if complete else None)
    else:
        mask = np.ones(len(ror), dtype=bool)
    valid = ror.loc[ror.physical_tof_valid.astype(bool)]
    cols = ["ror_x_mm", "ror_y_mm", "ror_z_mm"]
    metrics["all_valid_centroid_mm"] = valid[cols].mean().tolist() if len(valid) else None
    if source_mm is not None:
        # 對真配對量測單事件解析度；隨機符合另列，避免用平均值掩蓋分布。
        truth_ror = ror.loc[mask & ror.physical_tof_valid.astype(bool), cols]
        metrics["source_mm"] = list(source_mm)
        if len(truth_ror):
            points = truth_ror.to_numpy(float)
            error = points - np.asarray(source_mm)
            centroid = points.mean(axis=0)
            metrics.update({
                "truth_valid_centroid_mm": centroid.tolist(),
                "truth_centroid_error_mm": float(np.linalg.norm(centroid-source_mm)),
                "truth_event_rmse_mm": float(np.sqrt(np.mean(np.sum(error**2, axis=1)))),
                "truth_event_median_error_mm": float(np.median(np.linalg.norm(error, axis=1))),
            })
    return metrics
