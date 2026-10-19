"""依本機實際輸出建立繁體中文報告，並保存精簡結果供 Git 追蹤。"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]


def load(relative):
    return json.loads((PROJECT / relative).read_text(encoding="utf-8-sig"))


def coordinate(values):
    return "(" + ", ".join(f"{value:.3f}" for value in values) + ")"


def main():
    report_dir = PROJECT / "reports"
    report_dir.mkdir(exist_ok=True)
    metrics = load("outputs/synthetic/metrics.json")
    valid = load("outputs/validation.json")
    manifest = load("outputs/synthetic/manifest.json")
    settings = load("outputs/synthetic/config.json")
    sim_cfg, cuts = settings["simulation"], settings["coincidence"]
    sweep = pd.read_csv(PROJECT / "outputs/timing_sweep.csv")
    pytest_text = (PROJECT / "outputs/pytest.txt").read_text(encoding="utf-8-sig")
    passed = re.search(r"(\d+) passed", pytest_text)
    if not passed or re.search(r"\d+ failed|\d+ errors?", pytest_text):
        raise RuntimeError("pytest 紀錄未證實完整通過，不生成成功報告")
    for src, target in [
        ("outputs/validation.json", "software_validation.json"),
        ("outputs/timing_sweep.csv", "timing_sweep.csv"),
        ("outputs/pytest.txt", "pytest.txt"),
        ("outputs/synthetic/ror_projections.png", "synthetic_ror.png"),
    ]:
        shutil.copyfile(PROJECT / src, report_dir / target)
    for name in ("metrics.json", "config.json", "manifest.json"):
        shutil.copyfile(PROJECT / "outputs/synthetic" / name, report_dir / f"synthetic_{name}")
    today = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
    lines = [
        "# PET 軟體驗證與第一階段研究結果",
        "",
        f"實驗日期：{today}（Asia/Taipei）。本報告由 `scripts/build_report.py` 讀取實際輸出產生。",
        "",
        "## 環境與驗證方法",
        "",
        "本機使用新建並實際啟用的 Conda `pet-simulation` 環境。",
        f"Python：`{manifest['python'].splitlines()[0]}`。",
        f"程式版本：`{manifest['git_revision']}`；執行時工作目錄有變更：`{manifest['git_dirty']}`。",
        "完整程式 SHA-256、套件版本及輸出雜湊見 [manifest](synthetic_manifest.json)。",
        "",
        f"- 本機 pytest：**{passed.group(1)} 項通過**，原始紀錄見 [pytest.txt](pytest.txt)。",
        "- Ruff 靜態檢查另以命令列執行；GitHub Actions 會重跑靜態檢查、測試與解析驗證。",
        f"- 獨立暴力 oracle：{valid['oracle_singles']} 筆 Singles、{valid['oracle_pairs']} 組配對，與滑動視窗完全相同；打亂輸入順序仍相同。",
        f"- 零時間雜訊：{valid['noiseless_true_pairs']} 組真配對均找回，最大定位誤差 {valid['noiseless_max_error_mm']:.6f} mm，小於整數 ps 上限 {valid['integer_ps_error_bound_mm']:.6f} mm。",
        f"- 每端時間 σ=80 ps：實測定位 RMSE {valid['timing_rmse_mm']:.6f} mm，理論值 {valid['timing_expected_rmse_mm']:.6f} mm，相對差 {100 * valid['timing_relative_error']:.4f}%。",
        "",
        "這些檢查驗證配對、單位、正負號、端點互換、量化與誤差傳播；沒有用 ground truth 建立配對。",
        "",
        "## 理想幾何 Singles 實驗",
        "",
        f"設定 seed {sim_cfg['seed']}；{sim_cfg['n_rings']}×{sim_cfg['detectors_per_ring']} detector、{sim_cfg['n_lanes']} lane，最大絕對時間差 {cuts['window_ps']} ps、能量 {cuts['energy_min_kev']}–{cuts['energy_max_kev']} keV、橫向角差至少 {cuts['min_angle_deg']}°，全配對政策。",
        "",
        "| 指標 | 實測結果 |",
        "|---|---|",
        f"| 未配對 Singles | {metrics['singles']:,} |",
        f"| Coincidence pairs | {metrics['coincidence_pairs']:,} |",
        f"| 真配對 / 假配對 | {metrics['true_pairs']:,} / {metrics['false_pairs']:,} |",
        f"| 真配對比例 | {100 * metrics['same_truth_event_fraction']:.3f}% |",
        f"| 相鄰抵達資料的時間戳逆序次數 | {metrics['adjacent_timestamp_inversions']:,} |",
        f"| 真正光源位置 mm | {coordinate(metrics['source_mm'])} |",
        f"| 有效真配對的重建平均位置 mm | {coordinate(metrics['truth_valid_centroid_mm'])} |",
        f"| 平均位置的三維偏差 | {metrics['truth_centroid_error_mm']:.4f} mm |",
        f"| 真配對單事件三維 RMSE | {metrics['truth_event_rmse_mm']:.4f} mm |",
        f"| 有效 / 非物理 TOF pairs | {metrics['physical_tof_valid_pairs']:,} / {metrics['coincidence_pairs'] - metrics['physical_tof_valid_pairs']:,} |",
        "",
        "![理想幾何 ROR 投影與定位誤差](synthetic_ror.png)",
        "",
        "圖中青色十字為已知光源。平均位置偏差與單一事件誤差需要分開解讀；平均值準確不代表單事件具有同等解析度。",
        "",
        "## 時間同步誤差掃描",
        "",
        "為隔離時鐘效應，本組實驗使用 4000 個幾何接受事件、100% 效率、無背景、10 kBq 條件接受事件率；x≥0 半環額外加入固定時間偏移。",
        "",
        "| 每端時間 σ ps | 半環偏移 ps | 中心偏差 mm | 單事件 RMSE mm |",
        "|---:|---:|---:|---:|",
    ]
    for row in sweep.itertuples(index=False):
        lines.append(
            f"| {row.timing_sigma_ps} | {row.hemisphere_offset_ps} | {row.centroid_error_mm:.3f} | {row.event_rmse_mm:.3f} |"
        )
    lines += [
        "",
        "完整數字見 [timing_sweep.csv](timing_sweep.csv)。固定時鐘偏移可造成空間中心偏差；獨立零均值時間抖動主要增加事件定位分布的寬度。",
        "",
    ]
    gate_metrics = PROJECT / "outputs/gate/metrics.json"
    if gate_metrics.exists():
        gate = load("outputs/gate/metrics.json")
        meta = load("data/raw/gate_demo/metadata.json")
        for src, target in [
            ("outputs/gate/ror_projections.png", "gate_ror.png"),
            ("data/raw/gate_demo/metadata.json", "gate_metadata.json"),
            ("data/raw/gate_demo/mapping.json", "gate_mapping.json"),
        ]:
            shutil.copyfile(PROJECT / src, report_dir / target)
        for name in ("metrics.json", "config.json", "manifest.json"):
            shutil.copyfile(PROJECT / "outputs/gate" / name, report_dir / f"gate_{name}")
        lines += [
            "## 真正的 OpenGATE / Geant4 實驗",
            "",
            f"OpenGATE {meta['opengate_version']}，{meta['detector']['crystals']} 個 BGO 晶體、偏心點光源 {coordinate(meta['source']['position_mm'])} mm；Geant4 電磁傳輸後產生 Hits，再經 digitizer 產生尚未配對的 Singles。",
            f"實際產生 {meta['actual_generated_events']:,} 個事件，輸出 {gate['singles']:,} 筆 Singles，Python 找到 {gate['coincidence_pairs']:,} 組配對，其中 {gate.get('same_truth_event_pairs', 0):,} 組屬於同一個模擬源事件。",
            "",
            "EventID 相同不能證明未發生晶體散射，因此同事件比例是檢查指標，不是經完整 scatter/random 分類的 true-coincidence precision。",
            "數值、ROOT branches、版本、設定及原始資料雜湊見 [metadata](gate_metadata.json)、[metrics](gate_metrics.json)。",
            "",
            "![OpenGATE ROR 投影與同源事件定位誤差](gate_ror.png)",
            "",
            "重現指令（請在專案根目錄與已啟用的環境執行）：",
            "",
            "```powershell",
            "python scripts/generate_gate_singles.py --output data/raw/gate_demo --expected-events 30000",
            "pet-sim inspect-root data/raw/gate_demo/singles.root",
            "pet-sim import-root data/raw/gate_demo/singles.root --tree Singles --mapping data/raw/gate_demo/mapping.json --out data/processed/gate_singles.csv",
            "pet-sim run data/processed/gate_singles.csv --source-mm 30 -15 10 --out outputs/gate",
            "```",
            "",
            "既有 singles.root 不會覆寫；重新生成請更換 --output，並同步修改後續路徑。",
            "",
        ]
        if "same_event_valid_centroid_mm" in gate:
            lines += [
                f"有效同源事件配對的平均重建位置為 {coordinate(gate['same_event_valid_centroid_mm'])} mm；相對已知光源的中心偏差為 {gate['same_event_centroid_error_mm']:.4f} mm，單事件三維 RMSE 為 {gate['same_event_event_rmse_mm']:.4f} mm。這些值保留晶體散射與位置加總效應。",
                "",
            ]
    lines += [
        "## 如何重現簡化流程",
        "",
        "```powershell",
        ". .\\scripts\\activate.ps1",
        "New-Item -ItemType Directory -Force outputs | Out-Null",
        "python -m pytest -q | Tee-Object outputs/pytest.txt",
        "python -m pet_sim.cli validate",
        "python -m pet_sim.cli demo",
        "python -m pet_sim.cli sweep",
        "python scripts/build_report.py",
        "```",
        "",
        "## 結論與下一步",
        "",
        "已建立可重現、可檢查的離線 Singles → Coincidence → TOF-ROR 中心點累積流程。排序與配對通過獨立參考，TOF 計算符合解析量化及雜訊理論；時間偏移實驗提供後續同步研究的基準。",
        "",
        "目前尚未實作有限寬度 ROR 核、MLEM/OSEM、完整 PET 校正及串流 reorder/watermark，也未量測 FPGA 吞吐量。本機原始 ROOT 與完整事件 CSV 保存在 data/ 與 outputs/；GitHub 保存程式、測試、文件與這份精簡證據。",
        "",
        "研究模型與限制請一併閱讀 [README](../README.md) 及 [原始來源](../docs/sources.md)。",
        "",
    ]
    (report_dir / "validation_zh_TW.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"已產生報告：{report_dir / 'validation_zh_TW.md'}")


if __name__ == "__main__":
    main()
