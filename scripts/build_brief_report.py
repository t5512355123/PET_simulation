"""將既有 PET 報告改成白話短版；只整理已保存的結果，不重跑模擬。"""

import argparse
import base64
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from build_explainer_report import DEFAULT_APP, THEME

ROOT = Path(__file__).resolve().parents[1]

COPY = {
    "intro": "我們已完成一套 Python 程式，能從偵測紀錄找出可能的光子對，再估計光源位置。目前已跑通模擬流程。",
    "source": "資料由本機電腦產生。簡化模擬用幾何與隨機數產生事件；物理模擬用 OpenGATE／Geant4 計算光子與偵測器的互動。兩組都不是病患或實機掃描資料。",
    "steps": [
        {
            "title": "① 讀取偵測紀錄",
            "term": "Singles",
            "text": "每筆紀錄包含偵測時間、位置與能量。此時還沒有配對。",
        },
        {
            "title": "② 找到可能的一對",
            "term": "Coincidence",
            "text": "依時間、能量與位置條件，挑出可能來自同一次事件的兩筆紀錄。",
        },
        {
            "title": "③ 估計光源位置",
            "term": "ROR 中心",
            "text": "用兩端時間差計算一個位置，再把許多位置累積成分布圖。",
        },
    ],
    "result": "兩組資料都能完成這三步。事件對是通過篩選的候選組合，仍可能有誤配或散射。",
    "caption": "這是物理模擬的結果，從上方看光源位置。橘色十字是已知光源；藍點是各組配對估計的位置。點群靠近光源，但每次估計仍會分散。",
    "limit": "**已完成的是研究用的位置分布，還不是經完整校正的臨床影像。**",
    "next": "先把同一批資料交給 GATE 官方配對程式，逐對比較結果。確認一致後，再研究資料邊傳入、邊處理。現有 Python 程式可作為比較基準。",
    "date": "實驗資料：2026-10-19。本短版整理：2026-10-25。",
}

JSX = r"""import React from "react";
import { DataComponent, ReportSection, RichNarrative, useDataApp } from "../../data-app-public.jsx";
import content from "./brief.json";

export function ReportContent() {
  const { reviewedPeriodRows, appTitle, canEdit, mode, setAppTitle } = useDataApp();
  const rows = id => reviewedPeriodRows(id);
  return <article className="report-content brief-report" aria-label="PET 模擬簡明報告">
    <header className="brief-hero">
      <h1 data-data-app-title contentEditable={canEdit && mode === "edit"} suppressContentEditableWarning
        onBlur={canEdit && mode === "edit" ? e => setAppTitle(e.currentTarget.textContent.trim() || appTitle) : undefined}
        onKeyDown={e => { if (canEdit && mode === "edit" && e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); } }}>{appTitle}</h1>
    </header>
    <ReportSection id="brief-done" title="1. 做了什麼" queryId="summary" sourceRows={rows("summary")} showHeading={false}>
      <RichNarrative id="brief:done" value={`## 1. 做了什麼\n\n${content.copy.intro}`} />
    </ReportSection>
    <ReportSection id="brief-source" title="2. 資料從哪裡來" queryId="parameters" queryIds={["parameters", "gate_metadata"]}
      sourceRowsByQuery={{parameters: rows("parameters"), gate_metadata: rows("gate_metadata")}} showHeading={false}>
      <RichNarrative id="brief:source" value={`## 2. 資料從哪裡來\n\n${content.copy.source}`} />
    </ReportSection>
    <ReportSection id="brief-process" title="3. 程式怎麼處理" queryId="parameters" sourceRows={rows("parameters")} showHeading={false}>
      <RichNarrative id="brief:process-heading" value="## 3. 程式怎麼處理" />
      <ol className="brief-steps" aria-label="三步處理流程">
        {content.copy.steps.map((step, i) => <li key={step.term}>
          <RichNarrative id={`brief:step:${i}`} value={`### ${step.title}\n\n**${step.term}**\n\n${step.text}`} />
        </li>)}
      </ol>
    </ReportSection>
    <ReportSection id="brief-results" title="4. 結果如何" queryId="summary" sourceRows={rows("summary")} showHeading={false}>
      <RichNarrative id="brief:results-heading" value="## 4. 結果如何" />
      <div className="brief-table-wrap"><table aria-label="兩組模擬結果" data-reviewed-rows>
        <thead><tr><th scope="col">資料</th><th scope="col">偵測紀錄</th><th scope="col">找到的事件對</th></tr></thead>
        <tbody>{rows("summary").map((row, i) => <tr key={row.dataset}><th scope="row">{i === 0 ? "簡化模擬" : "物理模擬"}</th><td>{row.singles.toLocaleString("zh-TW")} 筆</td><td>{row.pairs.toLocaleString("zh-TW")} 組</td></tr>)}</tbody>
      </table></div>
      <RichNarrative id="brief:results-text" value={content.copy.result} />
      <DataComponent id="brief-position-map" title="物理模擬估計的位置" kind="custom" queryId="gate_pairs_all"
        queryIds={["gate_pairs_all", "summary"]} sourceRowsByQuery={{gate_pairs_all: rows("gate_pairs_all"), summary: rows("summary").filter(row => row.dataset.includes("OpenGATE"))}}
        sourceRows={rows("gate_pairs_all")} displayRows={rows("gate_pairs_all").filter(row => row.physical_tof_valid)} variant="plain">
        <figure className="brief-figure">
          <img src={content.image} width="1260" height="720" alt="藍色估計位置分布在橘色已知光源附近，但各次估計仍有分散。" data-reviewed-rows />
          <figcaption><RichNarrative id="brief:position-caption" value={content.copy.caption} /></figcaption>
        </figure>
      </DataComponent>
      <RichNarrative id="brief:limit" value={content.copy.limit} />
    </ReportSection>
    <ReportSection id="brief-next" title="5. 下一步" queryId="validation" sourceRows={rows("validation")} showHeading={false}>
      <RichNarrative id="brief:next" value={`## 5. 下一步\n\n${content.copy.next}`} />
    </ReportSection>
    <footer className="brief-footer"><RichNarrative id="brief:date" value={content.copy.date} /></footer>
  </article>;
}
"""

CSS = """.report-page { --data-app-layout-intent: authored-report; --data-app-content-width: 800px; --data-app-report-prose-width: 800px; --data-app-layout-gutter: 36px; margin-inline: auto; padding: 30px var(--data-app-layout-gutter) 64px; }
.brief-report { color: var(--text); font-size: 17px; line-height: 1.75; }
.brief-report > * { min-width: 0; }
.brief-report .brief-hero { border-bottom: 3px solid #168875; padding-bottom: 12px; margin-bottom: 24px; }
.brief-report h1 { font-size: clamp(28px, 4vw, 38px); line-height: 1.4; margin: 0; }
.brief-report h2 { font-size: 23px; line-height: 1.4; color: #15695f; margin: 30px 0 12px; }
.brief-report h3 { font-size: 18px; line-height: 1.5; margin: 0 0 8px; color: #1b4567; }
.brief-report p { margin: 10px 0; }
.brief-report .brief-steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; list-style: none; padding: 0; margin: 16px 0; }
.brief-report .brief-steps > li { padding: 16px; border: 1px solid #dce8ee; background: #f1f7fa; border-radius: 10px; font-size: 16px; }
.brief-report .brief-table-wrap { max-width: 100%; overflow-x: auto; margin: 16px 0; }
.brief-report table { width: 100%; border-collapse: collapse; font-size: 16px; }
.brief-report th, .brief-report td { padding: 12px 14px; border-bottom: 1px solid #dce4ef; white-space: nowrap; }
.brief-report thead th { background: #edf4fa; }
.brief-report th { text-align: left; font-weight: 600; }
.brief-report th:not(:first-child), .brief-report td { text-align: right; }
.brief-report .brief-figure { margin: 12px 0; }
.brief-report .brief-figure img { width: 100%; height: auto; display: block; }
.brief-report figcaption { font-size: 15px; color: #52647b; }
.brief-report .brief-footer { font-size: 13px; color: #6b7b8d; border-top: 1px solid #dce4ef; margin-top: 30px; padding-top: 12px; }
@media (max-width: 650px) {
 .report-page { --data-app-layout-gutter: 20px; padding-top: 20px; }
 .brief-report .brief-steps { grid-template-columns: 1fr; gap: 8px; }
 .brief-report .brief-steps > li { padding: 12px 16px; }
 .brief-report th, .brief-report td { padding: 10px; font-size: 14px; }
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP)
    parser.add_argument("--complete", action="store_true")
    args = parser.parse_args()
    data_path = args.app_dir / "src/data.json"
    snapshot = json.loads(data_path.read_text(encoding="utf-8-sig"))
    pairs_path = ROOT / "outputs/gate/coincidences_ror.csv"
    pairs = pd.read_csv(pairs_path)
    valid = pairs.loc[pairs.physical_tof_valid]
    metrics = json.loads((ROOT / "reports/gate_metrics.json").read_text(encoding="utf-8"))
    sx, sy, _ = metrics["source_mm"]
    plt.rcParams.update(
        {"font.sans-serif": ["Microsoft JhengHei", "DejaVu Sans"], "axes.unicode_minus": False}
    )
    fig, ax = plt.subplots(figsize=(7, 4), dpi=180, layout="constrained")
    ax.scatter(
        valid.ror_x_mm,
        valid.ror_y_mm,
        s=8,
        alpha=0.25,
        color="#1673bc",
        label="估計位置",
        edgecolors="none",
    )
    ax.scatter(
        [sx],
        [sy],
        s=140,
        marker="X",
        color="#df7b17",
        edgecolors="white",
        linewidths=1,
        label="已知光源",
        zorder=5,
    )
    ax.set_xlabel("左右位置（毫米）")
    ax.set_ylabel("前後位置（毫米）")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(alpha=0.15)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper right", frameon=False)
    assets = ROOT / "reports/brief_assets"
    assets.mkdir(exist_ok=True)
    png = assets / "gate_positions.png"
    fig.savefig(png, facecolor="white")
    plt.close(fig)
    png_bytes = png.read_bytes()
    manifest = {
        "created_at": "2026-10-25",
        "experiment_as_of": "2026-10-19",
        "source": str(pairs_path.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(pairs_path.read_bytes()).hexdigest(),
        "selection": "physical_tof_valid; no truth-based event selection",
        "pairs": len(valid),
        "source_xy_mm": [sx, sy],
        "image_sha256": hashlib.sha256(png_bytes).hexdigest(),
        "new_simulation_executed": False,
    }
    (assets / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    target = args.app_dir / "src/content/report"
    content = {
        "copy": COPY,
        "image": "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii"),
    }
    (target / "brief.json").write_text(
        json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target / "ReportContent.jsx").write_text(JSX.replace(r"\n", "\n"), encoding="utf-8")
    (target / "report.css").write_text(CSS, encoding="utf-8")
    (args.app_dir / "src/theme.css").write_text(THEME, encoding="utf-8")
    # 保留原報告識別碼與完整查核資料，只改正文與呈現。
    snapshot["title"] = "PET 模擬簡明報告"
    snapshot["generatedAt"] = "2026-10-25"
    snapshot["buildStatus"] = "complete" if args.complete else "updating"
    snapshot["report"]["asOf"] = "2026-10-19"
    data_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "sections": 5,
                "chart_count": 1,
                "artifact_id": snapshot["id"],
                "build_status": snapshot["buildStatus"],
                "new_simulation": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
