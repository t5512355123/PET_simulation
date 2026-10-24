"""整理既有實驗證據，供離線 HTML 說明報告使用；不重跑 PET 模擬。"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def read_json(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8-sig"))


def source(label, files, definitions=None):
    return {
        "label": label,
        "files": files,
        "executedAt": "2026-10-24",
        "dataAsOf": "2026-10-19",
        "metricDefinitions": definitions or [],
        "evidenceFlow": [
            {"title": "讀取原始證據", "detail": "讀取本機既有 JSON/CSV 與程式，不重新生成事件。"},
            {
                "title": "辨識日期",
                "detail": "2026-10-19 是實驗日期；2026-10-24 是說明報告整理日期。",
            },
        ],
    }


def frame_rows(frame):
    """保留全筆資料，將缺值轉為 JSON null，避免輸出不合法的 NaN。"""
    return json.loads(frame.to_json(orient="records", double_precision=15))


def full_record_query(frame, label, path):
    """標示全筆原始紀錄的來源範圍，避免誤把抽樣表當作整個圖的證據。"""
    provenance = source(
        label,
        [path],
        [
            {
                "label": "全筆 raw 紀錄",
                "definition": (
                    f"載入來源 CSV 的全部 {len(frame):,} 筆，保留所有欄位；"
                    "沒有抽樣或彙總。缺值以 JSON null 表示。"
                ),
            }
        ],
    )
    provenance.update({"scope": "all_rows", "rowCount": len(frame), "isSample": False})
    return {"rows": frame_rows(frame), "source": provenance}


def main():
    syn = read_json("reports/synthetic_metrics.json")
    gate = read_json("reports/gate_metrics.json")
    summary = []
    for name, m, prefix in [
        ("理想幾何模擬", syn, "truth"),
        ("OpenGATE物理模擬", gate, "same_event"),
    ]:
        summary.append(
            {
                "dataset": name,
                "singles": m["singles"],
                "pairs": m["coincidence_pairs"],
                "physicalPairs": m["physical_tof_valid_pairs"],
                "sameEventPairs": m["same_truth_event_pairs"],
                "centroidErrorMm": m[f"{prefix}_centroid_error_mm"],
                "eventRmseMm": m[f"{prefix}_event_rmse_mm"],
                "sourceXmm": m["source_mm"][0],
                "sourceYmm": m["source_mm"][1],
                "sourceZmm": m["source_mm"][2],
            }
        )
    raw = pd.read_csv(ROOT / "outputs/synthetic/singles_arrival_order.csv")
    pairs = pd.read_csv(ROOT / "outputs/synthetic/coincidences_ror.csv")
    example = pairs.loc[pairs.same_truth_event].head(1)
    example_ids = [int(example.iloc[0].single_id_1), int(example.iloc[0].single_id_2)]
    selected = raw.loc[raw.single_id.isin(example_ids)]
    queries = {
        "summary": {
            "rows": summary,
            "source": source(
                "兩組既有模擬的實際輸出",
                ["reports/synthetic_metrics.json", "reports/gate_metrics.json"],
                [
                    {
                        "label": "中心偏差",
                        "definition": "先平均有效真配對／同源配對的XYZ座標，再計算與指定光源的歐氏距離；單位mm。",
                        "componentIds": ["results", "centroid", "summary"],
                    },
                    {
                        "label": "單事件三維RMSE",
                        "definition": "先計算各有效真配對／同源配對的三維位置誤差平方，再平均並開根號；單位mm。",
                        "componentIds": ["results", "centroid", "summary"],
                    },
                    {
                        "label": "GATE同源配對",
                        "definition": "EventID及RunID一致的pair，不等於完成散射分類的真符合。",
                        "componentIds": ["results", "gate"],
                    },
                ],
            ),
        },
        "sweep": {
            "rows": pd.read_csv(ROOT / "reports/timing_sweep.csv").to_dict("records"),
            "source": source(
                "固定seed之時間誤差掃描", ["reports/timing_sweep.csv", "src/pet_sim/validation.py"]
            ),
        },
        "validation": {
            "rows": [read_json("reports/software_validation.json")],
            "source": source(
                "獨立oracle與解析誤差驗證",
                ["reports/software_validation.json", "reports/pytest.txt", "tests/"],
            ),
        },
        "synthetic_events": {
            "rows": json.loads(raw.head(40).to_json(orient="records")),
            "source": source(
                "理想模型依抵達順序的前40筆實際Singles",
                ["outputs/synthetic/singles_arrival_order.csv"],
                [
                    {
                        "label": "前40筆",
                        "definition": "只用於亂序示意，不代表完整事件分布。",
                        "componentIds": ["arrival"],
                    }
                ],
            ),
        },
        "pair_example": {
            "rows": json.loads(example.to_json(orient="records")),
            "source": source(
                "第一個真配對的實際重建欄位", ["outputs/synthetic/coincidences_ror.csv"]
            ),
        },
        "pair_singles": {
            "rows": json.loads(selected.to_json(orient="records")),
            "source": source(
                "與範例配對相符的兩筆Singles", ["outputs/synthetic/singles_arrival_order.csv"]
            ),
        },
        "gate_metadata": {
            "rows": [read_json("reports/gate_metadata.json")],
            "source": source(
                "OpenGATE產生程式記錄之物理模型與ROOT檢查",
                ["reports/gate_metadata.json", "scripts/generate_gate_singles.py"],
            ),
        },
        "parameters": {
            "rows": [
                read_json("reports/synthetic_config.json"),
                read_json("reports/gate_config.json"),
            ],
            "source": source(
                "兩組模型與coincidence篩選設定",
                ["reports/synthetic_config.json", "reports/gate_config.json"],
            ),
        },
    }
    # 完整逐筆查詢供全資料圖追溯；既有前40筆示意查詢保持原樣。
    gate_raw = pd.read_csv(ROOT / "outputs/gate/singles_arrival_order.csv")
    gate_pairs = pd.read_csv(ROOT / "outputs/gate/coincidences_ror.csv")
    for query_id, frame, label, path in [
        (
            "synthetic_singles_all",
            raw,
            "理想幾何全筆 raw Singles（既有 CSV 全部紀錄）",
            "outputs/synthetic/singles_arrival_order.csv",
        ),
        (
            "gate_singles_all",
            gate_raw,
            "OpenGATE全筆 raw Singles（標準化 CSV 全部紀錄）",
            "outputs/gate/singles_arrival_order.csv",
        ),
        (
            "synthetic_pairs_all",
            pairs,
            "理想幾何全筆 raw coincidence/ROR 紀錄（含假配對及非物理 TOF）",
            "outputs/synthetic/coincidences_ror.csv",
        ),
        (
            "gate_pairs_all",
            gate_pairs,
            "OpenGATE全筆 raw coincidence/ROR 紀錄（保留全部配對欄位）",
            "outputs/gate/coincidences_ror.csv",
        ),
    ]:
        queries[query_id] = full_record_query(frame, label, path)

    with np.load(ROOT / "outputs/synthetic/ror_volume.npz") as volume:
        counts = volume["counts"]
        voxel_rows = [
            {"ix": int(ix), "iy": int(iy), "iz": int(iz), "count": int(counts[ix, iy, iz])}
            for ix, iy, iz in np.argwhere(counts != 0)
        ]
        voxel_source = source(
            "理想幾何 NPZ 全部非零體素（索引與計數，不是逐筆事件）",
            ["outputs/synthetic/ror_volume.npz", "src/pet_sim/pipeline.py"],
            [
                {
                    "label": "非零體素",
                    "definition": (
                        "rows 的 ix、iy、iz 為零起算的 x/y/z 體素索引，count 為格內點數；"
                        "省略零體素但保留全部非零體素。只累積物理 TOF 有效且位於範圍內的 ROR 中心。"
                    ),
                }
            ],
        )
        voxel_source.update(
            {
                "shape": list(counts.shape),
                "axisOrder": ["x", "y", "z"],
                "edges": {
                    "x_mm": volume["x_edges_mm"].tolist(),
                    "y_mm": volume["y_edges_mm"].tolist(),
                    "z_mm": volume["z_edges_mm"].tolist(),
                },
                "total": int(counts.sum()),
                "scope": "all_nonzero_voxels",
                "rowCount": len(voxel_rows),
            }
        )
    queries["voxel"] = {"rows": voxel_rows, "source": voxel_source}

    figure_rows = read_json("reports/explainer_assets/manifest.json")["figures"]
    figure_source = source(
        "全圖圖說與來源索引（不是逐筆事件資料）",
        ["reports/explainer_assets/manifest.json", "scripts/create_explainer_figures.py"],
        [
            {
                "label": "圖說來源索引",
                "definition": (
                    "每一 row 是一幅圖的標題、圖說、來源與輸出證據，"
                    "不代表一筆 Singles、pair 或體素。逐筆數據圖仍須綁定對應的全筆事件查詢。"
                ),
            }
        ],
    )
    figure_source.update(
        {
            "dataAsOf": "2026-10-24",
            "scope": "all_figure_manifest_rows",
            "rowCount": len(figure_rows),
        }
    )
    queries["figure_evidence"] = {"rows": figure_rows, "source": figure_source}

    illustration_rows = [
        {
            "illustration_id": "tof_formula",
            "label": "教學用 TOF 端點與時間差操作範圍",
            "is_experiment": False,
            "L_mm": 800.0,
            "c_mm_per_ps": 0.299792458,
            "dt_min_ps": -4000.0,
            "dt_max_ps": 4000.0,
            "formula": "u=(p2-p1)/L; r=(p1+p2)/2-c*(t2-t1)*u/2",
        },
        {
            "illustration_id": "ctr_formula",
            "label": "教學用 CTR 與 Gaussian 空間 FWHM 換算",
            "is_experiment": False,
            "c_mm_per_ps": 0.299792458,
            "ctr_fwhm_ps": 200.0,
            "single_channel_fwhm_ps": 200.0 / math.sqrt(2),
            "spatial_fwhm_mm": 0.299792458 * 200.0 / 2,
        },
        {
            "illustration_id": "single_channel_sigma_formula",
            "label": "教學用獨立單端時間 sigma 與位置 sigma 換算",
            "is_experiment": False,
            "c_mm_per_ps": 0.299792458,
            "single_channel_sigma_ps": 80.0,
            "delta_t_sigma_ps": math.sqrt(2) * 80.0,
            "longitudinal_sigma_mm": 0.299792458 * 80.0 / math.sqrt(2),
        },
    ]
    illustration_source = source(
        "教學公式參數（非實驗事件，也不是新的模擬結果）",
        ["src/pet_sim/reconstruction.py", "src/pet_sim/config.py", "docs/sources.md"],
        [
            {
                "label": "獨立教學範例",
                "definition": (
                    "TOF 的 L=800 mm、Δt±4000 ps 是互動教學設定；CTR=200 ps FWHM"
                    "與單端 sigma=80 ps 為兩個獨立公式範例，不表示同一組實驗設定。"
                    "當 |cΔt|>L 時，教學位置落在線段外，不能因此宣稱是物理有效配對。"
                ),
            }
        ],
    )
    illustration_source.update({"dataAsOf": "2026-10-24", "scope": "teaching_formula_parameters"})
    queries["illustrations"] = {"rows": illustration_rows, "source": illustration_source}

    audit_source = source(
        "完整事實盤點與證據底稿（單列文件，不是逐筆事件）",
        ["docs/html_report_evidence.json"],
    )
    audit_source.update({"dataAsOf": "2026-10-24", "scope": "complete_evidence_document"})
    queries["audit"] = {
        "rows": [read_json("docs/html_report_evidence.json")],
        "source": audit_source,
    }
    snapshot = {
        "surface": "report",
        "title": "PET 軟體驗證完整說明：從單次偵測到三維位置",
        "generatedAt": "2026-10-24",
        "status": "reviewed",
        "buildStatus": "creating",
        "filters": [],
        "queries": queries,
    }
    out = ROOT / "docs/pet_explainer_snapshot.json"
    out.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(out)


if __name__ == "__main__":
    main()
