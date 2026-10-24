"""將可查核的正文與圖表放入共享報告框架；不修改框架與 PET 實驗。"""

import argparse
import base64
import json
import re
import struct
from pathlib import Path

from pet_explainer_content import chapters

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APP = Path.home() / "我的雲端硬碟/PET_HTML報告原始檔_2026-10-24"

# 圖片名稱以實際 manifest 為準；正文使用較容易閱讀的概念名稱。
ALIASES = {
    "04_tof_geometry": "04_tof_sign",
    "06_lane_delays": "06_lane_delay",
    "07_energy_windows": "07_energy_window",
    "08_time_differences": "08_dt_distribution",
    "13_error_distributions": "13_localization_errors",
    "15_timing_rmse": "15_timing_rmse_sweep",
    "16_timing_bias": "16_clock_bias_sweep",
    "18_tof_uncertainty": "18_ctr_uncertainty",
    "19_units_precision": "19_timestamp_precision",
}

FIGURE_QUERIES = {
    "01_pipeline": ["parameters", "summary"],
    "02_synthetic_geometry": ["parameters"],
    "03_gate_geometry": ["gate_metadata"],
    "04_tof_sign": ["illustrations"],
    "05_arrival_order": ["synthetic_events"],
    "06_lane_delay": ["synthetic_singles_all"],
    "07_energy_window": ["synthetic_singles_all", "gate_singles_all"],
    "08_dt_distribution": ["synthetic_pairs_all", "gate_pairs_all"],
    "09_pair_composition": ["synthetic_pairs_all", "gate_pairs_all"],
    "10_pair_matrix": ["synthetic_singles_all", "synthetic_pairs_all"],
    "11_synthetic_ror": ["synthetic_pairs_all"],
    "12_gate_ror": ["gate_pairs_all"],
    "13_localization_errors": ["synthetic_pairs_all", "gate_pairs_all"],
    "14_centroid_vs_spread": ["synthetic_pairs_all", "gate_pairs_all"],
    "15_timing_rmse_sweep": ["sweep"],
    "16_clock_bias_sweep": ["sweep"],
    "17_voxel_slices": ["voxel"],
    "18_ctr_uncertainty": ["illustrations"],
    "19_timestamp_precision": ["illustrations"],
    "20_stage_counts": ["summary", "gate_metadata", "parameters"],
}

JSX = r"""import React, { useState } from "react";
import { DataComponent, ReportSection, RichNarrative, useDataApp } from "../../data-app-public.jsx";
import book from "./book.json";

// 共享敘事元件處理一般 Markdown；表格使用原生語意欄列，避免顯示成直線文字。
function BookNarrative({ chapter }) {
  return chapter.blocks.map((block, bi) => block.type === "text"
    ? <RichNarrative key={bi} id={`pet:${chapter.id}:body:${bi}`} value={block.text} />
    : <table key={bi} className="pet-reference-table" aria-label={`${chapter.title}對照表`}>
      <thead><tr>{block.rows[0].map((cell, ci) => <th key={ci} scope="col"><RichNarrative id={`pet:${chapter.id}:t${bi}:h${ci}`} value={cell} /></th>)}</tr></thead>
      <tbody>{block.rows.slice(1).map((row, ri) => <tr key={ri}>{row.map((cell, ci) => <td key={ci} style={{textAlign:block.align[ci] === "right" ? "right" : "left"}}>
        <RichNarrative id={`pet:${chapter.id}:t${bi}:r${ri}:c${ci}`} value={cell} />
      </td>)}</tr>)}</tbody>
    </table>);
}

function TofDemonstrator() {
  const [dt, setDt] = useState(0);
  const c = 0.299792458;
  const x = -c * dt / 2;
  const valid = Math.abs(c * dt) <= 800;
  const screenX = (p) => 65 + (p + 650) / 1300 * 870;
  return <div className="pet-tof">
    <RichNarrative id="tof:interactive:intro" value="### 動手試：時間差怎麼改變位置？\n\n這是公式教具。兩個偵測器固定在 x = −400 mm 與 +400 mm。請移動滑桿。正的 Δt 表示第 2 端比較晚收到光子，因此位置向第 1 端移動。這裡沒有產生新的模擬事件。" />
    <label className="pet-range-label" htmlFor="pet-dt" data-reviewed-rows>時間差 Δt = t₂ − t₁：<strong>{dt.toLocaleString()} ps</strong></label>
    <input id="pet-dt" type="range" min="-4000" max="4000" step="10" value={dt} onChange={e => setDt(Number(e.target.value))} />
    <div className="pet-presets" aria-label="選擇時間差範例">
      {[-4000, -100, 0, 100, 4000].map(n => <button key={n} type="button" onClick={() => setDt(n)}>{n > 0 ? "+" : ""}{n} ps</button>)}
    </div>
    <svg viewBox="0 0 1000 205" role="img" data-reviewed-rows aria-label={`教學位置為 ${x.toFixed(2)} mm，${valid ? "在偵測器線段內" : "超出偵測器線段"}`}>
      <line x1="65" y1="100" x2="935" y2="100" stroke="#bdc9d8" strokeWidth="3" />
      <line x1={screenX(-400)} y1="100" x2={screenX(400)} y2="100" stroke="#1673bc" strokeWidth="8" />
      {[-400, 0, 400].map(p => <g key={p}><line x1={screenX(p)} y1="92" x2={screenX(p)} y2="118" stroke="#425870" /><text x={screenX(p)} y="152" textAnchor="middle">{p} mm</text></g>)}
      <rect x={screenX(-400)-10} y="69" width="20" height="62" rx="4" fill="#1673bc" />
      <rect x={screenX(400)-10} y="69" width="20" height="62" rx="4" fill="#1673bc" />
      <text x={screenX(-400)} y="40" textAnchor="middle">第 1 端 p₁</text>
      <text x={screenX(400)} y="40" textAnchor="middle">第 2 端 p₂</text>
      <circle cx={screenX(x)} cy="100" r="13" fill={valid ? "#00876f" : "#d87815"} stroke="white" strokeWidth="3" />
      <text x="500" y="191" textAnchor="middle">藍線：兩端之間的 LOR 線段；圓點：ROR 中心</text>
    </svg>
    <div className={`pet-tof-output ${valid ? "valid" : "invalid"}`} aria-live="polite" data-reviewed-rows>
      <strong>估計 x = {x.toFixed(3)} mm</strong>
      <span>{valid ? "符合 |c × Δt| ≤ L；仍不能單靠此條件證明真配對。" : "不符合 |c × Δt| ≤ L；程式保留 CSV，但不累積進體素。"}</span>
    </div>
    <RichNarrative id="tof:interactive:note" value="公式：x = −0.299792458 × Δt / 2。L = 800 mm 時，物理界線約為 |Δt| ≤ 2668.513 ps。4000 ps 配對門檻比這條界線寬，所以通過配對篩選仍可能得到無效 TOF。" />
  </div>;
}

export function ReportContent() {
  const { reviewedPeriodRows, visible, appTitle, canEdit, mode, setAppTitle } = useDataApp();
  const rows = query => reviewedPeriodRows(query);
  return <article className="report-content pet-book" aria-label="PET 軟體驗證完整教學報告">
    <header className="pet-cover">
      <RichNarrative id="pet:eyebrow" value="**研究紀錄 × 程式導讀 × 視覺教學**" />
      <h1 data-data-app-title contentEditable={canEdit && mode === "edit"} suppressContentEditableWarning
        onBlur={canEdit && mode === "edit" ? e => setAppTitle(e.currentTarget.textContent.trim() || appTitle) : undefined}
        onKeyDown={e => { if (canEdit && mode === "edit" && e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); } }}>{appTitle}</h1>
      <RichNarrative id="pet:deck" value="從 Raw list-mode Singles，走到 Coincidence、TOF 位置與三維 ROR 中心累積。\n\n**實驗證據：2026-10-19｜報告整理：2026-10-24｜繁體中文・淺色版・可離線閱讀**\n\n本報告採用簡短句子與固定名詞。你可以依序閱讀，也可以從目錄直接跳到結果、操作步驟或下一步。圖表與逐筆資料已封裝在檔案內。外部參考連結需要連網。" />
    </header>
    <nav className="pet-toc" aria-label="報告目錄">
      <RichNarrative id="pet:toc:title" value="## 閱讀目錄" />
      <ol>{book.chapters.map(ch => <li key={ch.id}><a href={`#pet-${ch.id}`}>{ch.title}</a></li>)}</ol>
    </nav>
    <div className="pet-chapters">
      {book.chapters.map(ch => visible(ch.id) && <section key={ch.id} id={`pet-${ch.id}`} className="pet-chapter">
        <ReportSection id={ch.id} title={ch.title} queryId={ch.query} sourceRows={rows(ch.query)} showHeading={false}>
          <BookNarrative chapter={ch} />
        </ReportSection>
        {ch.id === "tof" && <DataComponent id="pet-tof-demo" title="互動教具｜時間差與位置" kind="custom" queryId="illustrations" displayRows={rows("illustrations")} sourceRows={rows("illustrations")}><TofDemonstrator /></DataComponent>}
        {ch.figures.map(figId => {
          const fig = book.figures[figId];
          const ids = [...fig.queryIds, "figure_evidence"];
          const evidence = Object.fromEntries(ids.map(q => [q, q === "figure_evidence" ? rows(q).filter(f => f.id === fig.id) : rows(q)]));
          return visible(`pet-fig-${fig.id}`) && <DataComponent key={fig.id} id={`pet-fig-${fig.id}`} title={fig.title} kind="custom"
            queryId={ids[0]} queryIds={ids} sourceRowsByQuery={evidence} sourceRows={evidence[ids[0]]} displayRows={evidence[ids[0]]} variant="plain">
            <figure className="pet-figure">
              <a href={fig.dataUri} download={fig.png} title="下載這張圖的 PNG"><img src={fig.dataUri} alt={`${fig.title}。${fig.caption}`} width={fig.width} height={fig.height} data-reviewed-rows /></a>
              <figcaption><RichNarrative id={`pet:figure:${fig.id}:caption`} value={`**${fig.label}｜${fig.title}**\n\n${fig.caption}\n\n來源：${fig.sources.join("、")}。圖表右上方的來源選單可檢查已封裝資料與來源索引。`} /></figcaption>
            </figure>
          </DataComponent>;
        })}
        <a className="pet-back" href="#pet-reading-top">↑ 回到目錄</a>
      </section>)}
    </div>
  </article>;
}
"""

CSS = r""".report-page { --data-app-layout-intent: authored-report; --data-app-content-width: 1120px; --data-app-report-prose-width: 960px; --data-app-layout-gutter: 36px; margin-inline: auto; padding: 24px var(--data-app-layout-gutter) 100px; }
.pet-book { color: var(--text); line-height: 1.85; font-size: 17px; }
.pet-book .pet-cover { padding: 38px 0 30px; border-bottom: 3px solid #168875; margin-bottom: 32px; }
.pet-book .pet-cover h1 { font-size: clamp(30px, 4.5vw, 48px); line-height: 1.35; letter-spacing: -.02em; max-width: 960px; }
.pet-book .pet-cover > :first-child { color: #157968; letter-spacing: .08em; }
.pet-book .pet-toc { background: #edf4fa; border: 1px solid #d9e4ee; border-radius: 16px; padding: 22px 28px; margin: 0 0 42px; }
.pet-book .pet-toc ol { columns: 2; column-gap: 44px; padding-left: 24px; }
.pet-book .pet-toc li { margin: 0 0 9px; break-inside: avoid; }
.pet-book a { color: #1568a3; text-underline-offset: 3px; overflow-wrap: anywhere; }
.pet-book .pet-chapter { scroll-margin-top: 92px; padding-top: 24px; margin-bottom: 42px; border-top: 1px solid #dce4ef; min-width: 0; }
.pet-book .pet-chapter h2 { color: #163b5e; font-size: clamp(24px, 3vw, 31px); line-height: 1.5; margin-top: 12px; }
.pet-book .pet-chapter h3 { color: #146b62; font-size: 21px; margin-top: 32px; line-height: 1.6; }
.pet-book .pet-chapter p { margin: 14px 0; }
.pet-book .pet-chapter pre { background: #eef3f8; color: #213b55; border: 1px solid #d9e4ee; padding: 18px; border-radius: 10px; max-width: 100%; overflow-x: auto; font-size: 14px; line-height: 1.7; }
.pet-book .pet-chapter code { font-family: Consolas, "Microsoft JhengHei", monospace; overflow-wrap: anywhere; }
.pet-book .pet-chapter table { display: block; overflow-x: auto; max-width: 100%; border-collapse: collapse; font-size: 15px; line-height: 1.8; margin: 22px 0; }
.pet-book .pet-chapter th { background: #edf4fa; color: #193b59; }
.pet-book .pet-chapter th, .pet-book .pet-chapter td { padding: 10px 13px; border: 1px solid #dce4ef; min-width: 90px; vertical-align: top; }
.pet-book .pet-reference-table td p, .pet-book .pet-reference-table th p { margin: 0; }
.pet-book .pet-chapter blockquote { border-left: 4px solid #138977; background: #eff8f5; padding: 12px 20px; margin: 22px 0; }
.pet-book .pet-figure { margin: 20px 0 40px; }
.pet-book .pet-figure img { display: block; width: 100%; height: auto; background: white; border: 1px solid #e1e8ef; border-radius: 10px; }
.pet-book .pet-figure figcaption { color: #52647b; font-size: 14px; line-height: 1.8; padding: 8px 4px; }
.pet-book .pet-back { display: inline-block; font-size: 14px; margin-top: 20px; }
.pet-book .pet-tof { padding: 24px; border: 1px solid #c9dfe5; background: #f3faf9; border-radius: 14px; margin: 20px 0 32px; }
.pet-book .pet-tof svg { width: 100%; height: auto; margin-top: 12px; }
.pet-book .pet-tof svg text { font-size: 22px; fill: #334e68; }
.pet-book .pet-tof input { width: 100%; accent-color: #00876f; margin: 20px 0 10px; }
.pet-book .pet-range-label { display: block; font-size: 18px; }
.pet-book .pet-presets { display: flex; gap: 8px; flex-wrap: wrap; }
.pet-book .pet-presets button { background: white; color: #145f58; border: 1px solid #b8d3d1; border-radius: 7px; padding: 8px 12px; cursor: pointer; }
.pet-book .pet-presets button:focus-visible { outline: 3px solid #1673bc; outline-offset: 2px; }
.pet-book .pet-tof-output { display: flex; flex-wrap: wrap; gap: 10px 24px; padding: 14px; border-radius: 8px; background: #e3f2eb; }
.pet-book .pet-tof-output.invalid { background: #fff0da; color: #7e4608; }
@media (max-width: 700px) {
 .report-page { --data-app-layout-gutter: 20px; padding-top: 16px; }
 .pet-book { font-size: 16px; }
 .pet-book .pet-toc { padding: 16px 20px; }
 .pet-book .pet-toc ol { columns: 1; }
 .pet-book .pet-cover { padding-top: 20px; }
 .pet-book .pet-tof { padding: 14px; }
 .pet-book .pet-chapter td { min-width: 120px; }
}
@media print {
 .pet-book .pet-back, .pet-book .pet-presets, .pet-book .pet-tof input { display: none; }
 .pet-book .pet-figure { break-inside: avoid; }
 .pet-book .pet-toc { break-after: page; }
 .pet-book .pet-chapter table { display: table; font-size: 10px; }
 .pet-book .pet-chapter pre { white-space: pre-wrap; }
}
"""

THEME = r""":root {
 color-scheme: light;
 --adaptive-theme: 0;
 --font-sans-default: "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", "Segoe UI", sans-serif;
 --font-sans: var(--font-sans-default);
 --background: #fbfcfe; --surface: #ffffff; --surface-raised: #ffffff;
 --muted: #eef3f8; --control: #ffffff; --control-hover: #e8eff6;
 --interaction-hover: #eef3f8; --interaction-active: #e1eaf3;
 --text: #152b42; --secondary: #52647b; --border: #dce4ef; --border-strong: #bacbdc;
 --accent: #1568a3; --positive: #07856b; --negative: #bc3f35;
 --chart-1: #1673bc; --chart-2: #00876f; --chart-3: #d87815; --chart-4: #7964b4;
 --chart-5: #b34d76; --chart-6: #b68c0b; --chart-7: #bc3f35; --chart-8: #6e8095;
 --chart-neutral-fill: #eff3f8; --ranked-list-fill: #dcebf7; --ranked-list-fill-hover: #c6e1f4;
 --movement-positive: #07856b; --movement-negative: #bc3f35; --movement-total: #52647b;
 --card-radius: 16px; --data-card-radius: 16px; --data-card-background: #ffffff;
 --control-radius: 10px; --mark-radius: 6;
 --card-shadow: 0 4px 16px rgb(26 55 86 / 3%); --shadow: 0 8px 24px rgb(26 55 86 / 12%);
 --data-app-chrome-background: #ffffff; --data-app-chrome-text: #152b42;
 --dashboard-background: #fbfcfe;
}
"""


def narrative_blocks(markdown):
    """保留程式區塊，將 Markdown 表格轉成可存取的 HTML 欄列資料。"""
    lines = markdown.splitlines()
    blocks = []
    prose = []
    i = 0
    in_code = False

    def cells(line):
        return [
            s.strip().replace(r"\|", "|") for s in re.split(r"(?<!\\)\|", line.strip().strip("|"))
        ]

    def flush():
        if prose:
            blocks.append({"type": "text", "text": "\n".join(prose).strip()})
            prose.clear()

    while i < len(lines):
        if lines[i].lstrip().startswith("```"):
            in_code = not in_code
        next_cells = cells(lines[i + 1]) if i + 1 < len(lines) else []
        if (
            not in_code
            and lines[i].strip().startswith("|")
            and next_cells
            and all(re.fullmatch(r":?-{3,}:?", cell) for cell in next_cells)
        ):
            flush()
            rows = [cells(lines[i])]
            align = [
                "right" if cell.endswith(":") and not cell.startswith(":") else "left"
                for cell in next_cells
            ]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = cells(lines[i])
                if len(row) != len(rows[0]):
                    raise ValueError(f"表格欄數不同：{lines[i]}")
                rows.append(row)
                i += 1
            blocks.append({"type": "table", "rows": rows, "align": align})
        else:
            prose.append(lines[i])
            i += 1
    flush()
    return blocks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP)
    parser.add_argument("--complete", action="store_true")
    args = parser.parse_args()
    target = args.app_dir / "src/content/report"
    if not (args.app_dir / "AGENTS.md").is_file():
        raise SystemExit("請先使用 Data 報告工具建立共享框架。")
    target.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(
        (ROOT / "reports/explainer_assets/manifest.json").read_text(encoding="utf-8")
    )
    figures = {}
    kinds = {
        "empirical": "既有模擬輸出",
        "illustrative": "教學示意",
        "configuration_diagram": "模型設定圖",
        "analytical_illustration": "解析公式示意",
        "numerical_illustration": "數值表示示意",
    }
    for fig in manifest["figures"]:
        png = ROOT / "reports/explainer_assets" / fig["png"]
        png_bytes = png.read_bytes()
        width, height = struct.unpack(">II", png_bytes[16:24])
        figures[fig["id"]] = {
            **fig,
            "width": width,
            "height": height,
            "queryIds": FIGURE_QUERIES[fig["id"]],
            "label": kinds[fig["kind"]],
            "dataUri": "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii"),
        }
    content = chapters()
    for chapter in content:
        chapter["blocks"] = narrative_blocks(chapter["body"])
        chapter["figures"] = [ALIASES.get(i, i) for i in chapter["figures"]]
        # TOF 示意保留在公式章，避免重複占用篇幅。
        if chapter["id"] == "pet":
            chapter["figures"] = []
        if chapter["id"] == "synthetic":
            chapter["figures"] = [i for i in chapter["figures"] if i != "06_lane_delay"]
        if chapter["id"] == "arrival":
            chapter["figures"].append("06_lane_delay")
        if chapter["id"] in {"sources", "modules", "limitations", "references"}:
            chapter["query"] = "audit"
    book = {"chapters": content, "figures": figures}
    (target / "book.json").write_text(
        json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    jsx = re.sub(
        r'value="([^"]*)"',
        lambda match: (
            "value={" + json.dumps(match.group(1).replace(r"\n", "\n"), ensure_ascii=False) + "}"
        ),
        JSX,
    )
    (target / "ReportContent.jsx").write_text(
        jsx.replace('<nav className="pet-toc"', '<nav id="pet-reading-top" className="pet-toc"'),
        encoding="utf-8",
    )
    (target / "report.css").write_text(CSS, encoding="utf-8")
    (args.app_dir / "src/theme.css").write_text(THEME, encoding="utf-8")
    snapshot_path = args.app_dir / "src/data.json"
    existing = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
    snapshot = json.loads((ROOT / "docs/pet_explainer_snapshot.json").read_text(encoding="utf-8"))
    # 沿用框架分配的永久識別碼，不改變已保存的編輯狀態。
    for field in ("id", "legacyPresentationTitle", "authoredRevision"):
        if field in existing:
            snapshot[field] = existing[field]
    snapshot["report"] = {"asOf": "2026-10-19"}
    snapshot["buildStatus"] = "complete" if args.complete else "creating"
    snapshot_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "app": str(args.app_dir),
                "chapters": len(content),
                "figures": len(figures),
                "characters": sum(len(ch["body"]) for ch in content),
                "status": snapshot["buildStatus"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
