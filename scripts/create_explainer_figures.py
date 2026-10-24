"""以既有結果產生淺色 PET 教學圖；不重新執行物理模擬。

使用方式：python scripts/create_explainer_figures.py
輸出 SVG、150 dpi PNG 與包含資料路徑、雜湊、說明的 manifest。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import colors, font_manager
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle
from matplotlib.ticker import FuncFormatter
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "explainer_assets"
C = 0.299792458
BLUE, TEAL, ORANGE, PURPLE = "#2164ac", "#17877e", "#d78221", "#8051a5"
INK, GRAY, GRID = "#203047", "#68778a", "#e5eaf0"
FIGURES: list[dict] = []
INPUTS: dict[str, dict] = {}


def digest(path):
    """串流計算雜湊，保留圖表的實際輸入身分。"""
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def tracked(relative):
    path = ROOT / relative
    INPUTS[relative] = {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size}
    return path


def read_json(relative):
    return json.loads(tracked(relative).read_text(encoding="utf-8-sig"))


def configure_style():
    """使用實際存在的繁體中文字型，將 SVG 字型轉為路徑以便離線攜帶。"""
    choices = [Path("C:/Windows/Fonts/msjh.ttc"), Path("C:/Windows/Fonts/msjhbd.ttc")]
    existing = [p for p in choices if p.exists()]
    if not existing:
        raise RuntimeError("找不到 Microsoft JhengHei；請指定可用的繁體中文字型")
    for path in existing:
        font_manager.fontManager.addfont(str(path))
    family = font_manager.FontProperties(fname=str(existing[0])).get_name()
    plt.rcParams.update(
        {
            "font.family": [family, "DejaVu Sans"],
            "font.size": 11,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "figure.titlesize": 17,
            "legend.fontsize": 10,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
            "text.color": INK,
            "axes.labelcolor": INK,
            "axes.edgecolor": "#9ba8b8",
            "xtick.color": GRAY,
            "ytick.color": GRAY,
            "grid.color": GRID,
            "grid.linewidth": 0.7,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "path",
            "axes.unicode_minus": False,
            "lines.linewidth": 2,
            "patch.linewidth": 0.8,
            "mathtext.fontset": "dejavusans",
        }
    )
    return {
        "family": family,
        "fallback": "DejaVu Sans",
        "files": [str(p) for p in existing],
        "svg_fonttype": "path",
    }


def figure(title, nrows=1, ncols=1, figsize=(12, 5), **kwargs):
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, layout="constrained", **kwargs)
    fig.suptitle(title, color=INK, fontweight="bold")
    return fig, axes


def save(fig, key, title, caption, sources, kind="empirical", details=None):
    """保存同一圖形的向量與點陣版本及明確的證據範圍。"""
    OUT.mkdir(parents=True, exist_ok=True)

    # 使用純文字數值，避開數學排版預設字型不含負指數減號的情況。
    def log_label(value, position):
        return f"{value:.0e}" if value and (value >= 10000 or value < 0.001) else f"{value:g}"

    for axis in fig.axes:
        if axis.get_xscale() == "log":
            axis.xaxis.set_major_formatter(FuncFormatter(log_label))
        if axis.get_yscale() == "log":
            axis.yaxis.set_major_formatter(FuncFormatter(log_label))
    fig.savefig(OUT / f"{key}.svg", bbox_inches="tight", pad_inches=0.16)
    fig.savefig(OUT / f"{key}.png", dpi=150, bbox_inches="tight", pad_inches=0.16)
    plt.close(fig)
    FIGURES.append(
        {
            "id": key,
            "title": title,
            "caption": caption,
            "kind": kind,
            "svg": f"{key}.svg",
            "png": f"{key}.png",
            "sources": sources,
            "details": details or {},
            "output_sha256": {ext: digest(OUT / f"{key}.{ext}") for ext in ("svg", "png")},
        }
    )


def panel(ax, title, xlabel=None, ylabel=None):
    ax.set_title(title, loc="left", pad=10)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.grid(alpha=0.8, axis="y")
    ax.set_axisbelow(True)


def box(ax, x, y, w, h, text, color=BLUE):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.015,rounding_size=0.025",
        edgecolor=color,
        facecolor=colors.to_rgba(color, 0.07),
        linewidth=1.2,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=11, color=INK)


def arrow(ax, start, end, color=GRAY, **kwargs):
    ax.add_patch(
        FancyArrowPatch(
            start, end, arrowstyle="-|>", mutation_scale=14, color=color, linewidth=1.5, **kwargs
        )
    )


def sources_and_frames():
    """只讀既存輸出；每個資料框均來自可核對的 CSV。"""
    config = read_json("reports/synthetic_config.json")
    gate_meta = read_json("reports/gate_metadata.json")
    syn_metrics = read_json("reports/synthetic_metrics.json")
    gate_metrics = read_json("reports/gate_metrics.json")
    for kind in ("synthetic", "gate"):
        read_json(f"outputs/{kind}/manifest.json")
    singles = {
        kind: pd.read_csv(tracked(f"outputs/{kind}/singles_arrival_order.csv"))
        for kind in ("synthetic", "gate")
    }
    pairs = {
        kind: pd.read_csv(tracked(f"outputs/{kind}/coincidences_ror.csv"))
        for kind in ("synthetic", "gate")
    }
    sweep = pd.read_csv(tracked("reports/timing_sweep.csv"))
    volume = np.load(tracked("outputs/synthetic/ror_volume.npz"))
    return config, gate_meta, syn_metrics, gate_metrics, singles, pairs, sweep, volume


def draw_pipeline():
    fig, ax = figure("示意圖｜兩種資料來源，共用一套配對與重建流程", figsize=(13, 6))
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    box(ax, 0.02, 0.68, 0.24, 0.19, "簡化圓筒幾何\nsimulation.py", BLUE)
    box(ax, 0.02, 0.22, 0.24, 0.19, "OpenGATE / Geant4\nHits → Digitizer → Singles", TEAL)
    box(ax, 0.35, 0.46, 0.25, 0.22, "統一 Singles 欄位\nint64 ps / mm / keV", BLUE)
    arrow(ax, (0.26, 0.77), (0.35, 0.59))
    arrow(ax, (0.26, 0.32), (0.35, 0.53))
    box(ax, 0.72, 0.66, 0.25, 0.18, "時間、能量、角度篩選\ncoincidence.py", BLUE)
    box(ax, 0.72, 0.35, 0.25, 0.18, "LOR + TOF → ROR 中心\nreconstruction.py", ORANGE)
    box(ax, 0.35, 0.04, 0.25, 0.18, "CSV / NPZ / PNG\nmetrics + manifest", PURPLE)
    arrow(ax, (0.60, 0.59), (0.72, 0.74))
    arrow(ax, (0.845, 0.66), (0.845, 0.53))
    arrow(ax, (0.72, 0.40), (0.60, 0.17))
    ax.text(0.475, 0.78, "truth 僅供事後評估\n不參與 coincidence 搜尋", ha="center", color=GRAY)
    save(
        fig,
        "01_pipeline",
        "兩種資料來源的共用軟體流程",
        "架構示意圖。上游模擬只負責產生未配對 Singles；真值事件編號不參與時間窗、能量或幾何搜尋。",
        [
            "src/pet_sim/simulation.py",
            "src/pet_sim/coincidence.py",
            "src/pet_sim/reconstruction.py",
        ],
        "illustrative",
    )


def draw_geometry(cfg, meta):
    sim = cfg["simulation"]
    source = np.array(sim["source_mm"])
    radius, rings, sectors = sim["radius_mm"], sim["n_rings"], sim["detectors_per_ring"]
    theta = (np.arange(sectors) + 0.5) * 2 * np.pi / sectors
    z_centers = (np.arange(rings) - (rings - 1) / 2) * sim["ring_pitch_mm"]
    fig = plt.figure(figsize=(12, 6), layout="constrained")
    fig.suptitle("幾何示意｜7 層 × 48 個 ID，互動位置保留連續交點", fontweight="bold")
    ax = fig.add_subplot(121, projection="3d")
    for ring, z in enumerate(z_centers):
        lane = (ring * sectors + np.arange(sectors)) % sim["n_lanes"]
        shade = [BLUE if v == 0 else ORANGE if v == 1 else "#bcc8d5" for v in lane]
        ax.scatter(
            radius * np.cos(theta), radius * np.sin(theta), np.full(sectors, z), c=shade, s=10
        )
        arc = np.linspace(0, 2 * np.pi, 180)
        ax.plot(
            radius * np.cos(arc), radius * np.sin(arc), np.full(len(arc), z), color=GRID, lw=0.7
        )
    ax.scatter(*source, marker="*", c=PURPLE, s=140, label="偏心光源")
    ax.set(xlabel="x (mm)", ylabel="y (mm)", zlabel="z (mm)")
    ax.set_box_aspect((1, 1, 0.55))
    ax.view_init(24, 36)
    ax.legend(loc="upper right")
    bx = fig.add_subplot(122)
    bx.add_patch(Circle((0, 0), radius, fill=False, edgecolor="#b8c5d3", lw=1.5))
    bx.scatter(
        radius * np.cos(theta), radius * np.sin(theta), s=26, c=BLUE, label="中層 ID 中心示意"
    )
    bx.scatter(*source[:2], marker="*", s=180, c=PURPLE, label="光源 (20, −12) mm")
    bx.annotate(
        "R = 400 mm",
        xy=(radius, 0),
        xytext=(70, 145),
        arrowprops={"arrowstyle": "->", "color": GRAY},
    )
    panel(bx, "橫向平面：ID 量化 ≠ 互動座標量化", "x (mm)", "y (mm)")
    bx.set_aspect("equal")
    bx.set(xlim=(-470, 470), ylim=(-470, 470))
    bx.legend(loc="lower left")
    save(
        fig,
        "02_synthetic_geometry",
        "簡化圓筒與偵測器 ID 幾何",
        "依保存的 SimulationConfig 繪製，並非實機設計。3D 圖藍／橙色標示 lane 0／1，其餘 lane 為灰色；圖中的 detector 中心只說明 ID，實際互動座標採連續圓筒交點。",
        ["reports/synthetic_config.json"],
        "configuration_diagram",
    )

    fig, axes = figure("幾何示意｜OpenGATE 的 96 個 BGO 晶體", ncols=2, figsize=(12, 5.5))
    ax, bx = axes
    detector = meta["detector"]
    radius = detector["center_radius_mm"]
    radial, tangential, axial = detector["crystal_size_radial_tangential_axial_mm"]
    corners = np.array(
        [
            [-radial / 2, -tangential / 2],
            [radial / 2, -tangential / 2],
            [radial / 2, tangential / 2],
            [-radial / 2, tangential / 2],
        ]
    )
    for phi in np.arange(detector["crystals"]) * 2 * np.pi / detector["crystals"]:
        rotation = np.array([[np.cos(phi), -np.sin(phi)], [np.sin(phi), np.cos(phi)]])
        coordinates = (corners + [radius, 0]) @ rotation.T
        ax.add_patch(Polygon(coordinates, facecolor="#c8e9e4", edgecolor=TEAL, linewidth=0.7))
    src = meta["source"]["position_mm"]
    ax.scatter(*src[:2], marker="*", s=180, c=PURPLE, label="光源 (30, −15) mm")
    panel(ax, "橫向佈局：20 × 10 mm 晶體截面", "x (mm)", "y (mm)")
    ax.set_aspect("equal")
    ax.set(xlim=(-235, 235), ylim=(-235, 235))
    ax.legend(loc="lower left")
    for center in (-radius, radius):
        bx.add_patch(
            Rectangle(
                (center - radial / 2, -axial / 2),
                radial,
                axial,
                facecolor="#c8e9e4",
                edgecolor=TEAL,
            )
        )
    bx.scatter(src[0], src[2], marker="*", c=PURPLE, s=180)
    bx.axhline(-axial / 2, color=GRID, ls="--")
    bx.axhline(axial / 2, color=GRID, ls="--")
    bx.text(0, 65, "晶體長度 100 mm\n半徑 200 mm", ha="center", color=GRAY)
    panel(bx, "x–z 側視截面", "x (mm)", "z (mm)")
    bx.set_aspect("equal")
    bx.set(xlim=(-235, 235), ylim=(-105, 105))
    save(
        fig,
        "03_gate_geometry",
        "OpenGATE 晶體配置",
        "依實際生成 metadata 的幾何參數繪製。BGO 晶體的徑向、切向、軸向尺寸為 20 × 10 × 100 mm；直接生成背對背光子，未模擬完整衰變或受測物。",
        ["reports/gate_metadata.json"],
        "configuration_diagram",
    )


def draw_tof():
    fig, ax = figure("解析示意｜到達時間差如何決定 LOR 上的位置", figsize=(12.5, 5.4))
    ax.set(xlim=(-525, 525), ylim=(-180, 230))
    ax.axis("off")
    ax.plot([-400, 400], [0, 0], color=GRAY, lw=2)
    for x, label in [(-400, "p1 = −400 mm"), (400, "p2 = +400 mm")]:
        ax.add_patch(Rectangle((x - 16, -35), 32, 70, facecolor="#dae8f7", edgecolor=BLUE))
        ax.text(x, -65, label, ha="center")
    ax.scatter(80, 0, marker="*", s=240, c=PURPLE, zorder=5)
    ax.scatter(0, 0, s=55, facecolors="white", edgecolors=GRAY, zorder=4)
    arrow(ax, (68, 25), (-365, 25), BLUE)
    arrow(ax, (92, 25), (365, 25), TEAL)
    ax.text(-180, 52, "路徑 480 mm；t1 = 1601.1 ps", ha="center", color=BLUE)
    ax.text(245, 105, "路徑 320 mm\nt2 = 1067.4 ps", ha="center", color=TEAL)
    arrow(ax, (-250, 165), (240, 165), GRAY)
    ax.text(0, 183, "u = (p2 − p1) / L，正方向朝 p2", ha="center")
    ax.text(80, -35, "源位置 +80 mm", ha="center", color=PURPLE)
    ax.text(0, -105, "dt = t2 − t1 = −533.7 ps；midpoint = 0 mm", ha="center", fontsize=12)
    ax.text(
        0, -150, "r = midpoint − (c × dt / 2) × u = +80 mm", ha="center", fontsize=15, color=BLUE
    )
    save(
        fig,
        "04_tof_sign",
        "TOF 位置公式與時間差符號",
        "解析示意，數字由 1D 幾何直接計算，並非實驗事件。來源靠近 p2，t2 較早、dt 為負，因此定位朝 p2 移動。交換兩端會同時反轉 u 與 dt，位置不變。",
        ["src/pet_sim/reconstruction.py"],
        "illustrative",
        {"example_source_x_mm": 80, "detectors_x_mm": [-400, 400]},
    )


def draw_stream(singles):
    frame = singles["synthetic"].head(40).copy()
    actual_rank = frame.timestamp_ps.rank(method="first").to_numpy() - 1
    arrival_rank = np.arange(len(frame))
    fig, axes = figure("實際資料｜傳輸抵達順序不同於偵測時間順序", ncols=2, figsize=(12, 5))
    ax, bx = axes
    ax.plot(arrival_rank, arrival_rank, "--", c=GRAY, lw=1, label="若兩種順序完全相同")
    ax.plot(arrival_rank, actual_rank, "o-", c=BLUE, markersize=4, label="實際偵測時間排名")
    panel(ax, "輸出串流前 40 筆", "抵達順序索引（0 起算）", "偵測時間排序索引（此 40 筆內）")
    ax.legend(loc="upper left")
    delay = (frame.arrival_time_ps - frame.timestamp_ps) / 1000
    bx.vlines(arrival_rank, 0, delay, color=BLUE, lw=1.4)
    bx.scatter(arrival_rank, delay, c=BLUE, s=24)
    panel(bx, "同一批資料的傳輸時間差", "抵達順序索引（0 起算）", "arrival − timestamp (ns)")
    bx.set_ylim(bottom=0)
    save(
        fig,
        "05_arrival_order",
        "抵達順序與量測時間順序",
        "讀取 synthetic CSV 最前 40 筆。左圖比較兩種排名；右圖直接相減得到傳輸延遲。這些延遲不應加入 coincidence 或 TOF 的量測時間差。各 lane 的分布另見下一圖。",
        ["outputs/synthetic/singles_arrival_order.csv"],
        details={"rows": 40},
    )

    frame = singles["synthetic"].copy()
    frame["delay_ns"] = (frame.arrival_time_ps - frame.timestamp_ps) / 1000
    groups = [g.delay_ns.to_numpy() for _, g in frame.groupby("lane_id", sort=True)]
    fig, ax = figure("實際資料｜14 個 lane 的固定延遲與到達抖動", figsize=(12, 5))
    boxes = ax.boxplot(
        groups,
        orientation="vertical",
        patch_artist=True,
        showfliers=False,
        tick_labels=[str(v) for v in sorted(frame.lane_id.unique())],
    )
    for patch in boxes["boxes"]:
        patch.set(facecolor="#d6e6f7", edgecolor=BLUE)
    for median in boxes["medians"]:
        median.set(color=BLUE, linewidth=1.8)
    panel(
        ax,
        "箱體為第 25–75 百分位；中線為中位數；鬚為 1.5 IQR 範圍",
        "lane_id",
        "arrival − timestamp (ns)",
    )
    ax.set_ylim(bottom=0)
    save(
        fig,
        "06_lane_delay",
        "各 lane 的實測模擬傳輸延遲",
        "由所有 15,871 筆 synthetic Singles 計算，不以設定上限代替實際延遲。箱型圖展示每 lane 固定延遲之上的抖動分布；不同 lane 的樣本數不同。",
        ["outputs/synthetic/singles_arrival_order.csv"],
        details={"counts_by_lane": frame.groupby("lane_id").size().to_dict()},
    )


def draw_energy_dt(singles, pairs, cfg):
    fig, axes = figure("實際資料｜能量回應與相同的 350–650 keV 篩選窗", ncols=2, figsize=(12, 5))
    for ax, kind, color, name in zip(
        axes, ("synthetic", "gate"), (BLUE, TEAL), ("簡化模型", "OpenGATE"), strict=True
    ):
        energy = singles[kind].energy_kev
        ax.axvspan(350, 650, color=color, alpha=0.08)
        ax.hist(energy, bins=np.arange(0, 825, 10), color=color, alpha=0.86)
        for cutoff in (350, 650):
            ax.axvline(cutoff, color=ORANGE, ls="--", lw=1.6)
        panel(
            ax, f"{name}：全部 {len(energy):,} 筆 Singles", "單端能量 (keV)", "Singles 數 / 10 keV"
        )
        ax.set_xlim(0, 800)
        ax.set_yscale("log")
        ax.set_ylim(bottom=0.7)
        passed = int(energy.between(350, 650).sum())
        ax.text(
            0.04,
            0.93,
            f"窗內 {passed:,} 筆\n{passed / len(energy):.1%}",
            transform=ax.transAxes,
            va="top",
        )
    save(
        fig,
        "07_energy_window",
        "Singles 能量與篩選窗",
        "實際 CSV 的能量分布；兩圖使用相同能量 bins 和對數計數軸。OpenGATE 中 511 keV 的峰來自完整能量沉積，其低能尾部由粒子傳輸產生；目前未另外加入能量解析度模型。",
        ["outputs/synthetic/singles_arrival_order.csv", "outputs/gate/singles_arrival_order.csv"],
    )

    fig, axes = figure("實際資料｜時間窗內的所有符合對，並不都是同事件", ncols=2, figsize=(12, 5))
    frame = pairs["synthetic"]
    true = frame.same_truth_event.astype(bool)
    axes[0].hist(
        frame.loc[true, "dt_ps"] / 1000,
        bins=np.linspace(0, 4, 81),
        histtype="step",
        lw=2,
        color=BLUE,
        label="同事件／synthetic 真配對",
    )
    axes[0].hist(
        frame.loc[~true, "dt_ps"] / 1000,
        bins=np.linspace(0, 4, 81),
        histtype="step",
        lw=2,
        color=ORANGE,
        label="不同事件／背景",
    )
    axes[0].axvline(4, c=GRAY, ls="--")
    axes[0].set_yscale("log")
    axes[0].set_ylim(bottom=0.7)
    panel(axes[0], "完整時間窗：保留所有合格 pairs", "dt = t2 − t1 (ns)", "pair 數 / 50 ps（對數）")
    axes[0].legend(loc="upper right")
    for kind, color, name in [("synthetic", BLUE, "簡化模型"), ("gate", TEAL, "OpenGATE")]:
        frame = pairs[kind]
        data = frame.loc[frame.same_truth_event.astype(bool), "dt_ps"]
        axes[1].hist(
            data,
            bins=np.arange(0, 1201, 30),
            density=True,
            histtype="step",
            lw=2,
            color=color,
            label=name,
        )
    panel(axes[1], "同事件時間差的細部比較", "dt = t2 − t1 (ps)", "機率密度 (1/ps)")
    axes[1].set_xlim(0, 1200)
    axes[1].legend()
    save(
        fig,
        "08_dt_distribution",
        "符合時間差分布",
        "符合器將第一端定義為時間較早者，因此輸出 dt 非負。4000 ps 是最大絕對時間差；同事件分布同時包含偏心源的飛行路徑差與時間誤差，不能直接當成 CTR。",
        [
            "outputs/synthetic/coincidences_ror.csv",
            "outputs/gate/coincidences_ror.csv",
            "reports/synthetic_config.json",
        ],
    )


def draw_pair_structure(pairs, singles):
    syn = pairs["synthetic"]
    same = syn.same_truth_event.astype(bool)
    valid = syn.physical_tof_valid.astype(bool)
    counts = [
        int((same & valid).sum()),
        int((~same & valid).sum()),
        int((same & ~valid).sum()),
        int((~same & ~valid).sum()),
    ]
    fig, axes = figure(
        "實際資料｜符合的 truth 關係與物理 TOF 有效性分開判斷", ncols=2, figsize=(12, 5)
    )
    names = ["同事件・有效 TOF", "不同事件・有效 TOF", "同事件・無效 TOF", "不同事件・無效 TOF"]
    ax = axes[0]
    y = np.arange(4)
    ax.barh(y, counts, color=[BLUE, ORANGE, "#a9c4df", "#ebc59a"])
    for i, count in enumerate(counts):
        ax.text(count + 85, i, f"{count:,}", va="center")
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    ax.set_xlim(0, max(counts) * 1.19)
    panel(ax, "簡化模型：7,262 對", "pair 數")
    ax = axes[1]
    proportions = [same.mean(), pairs["gate"].same_truth_event.astype(bool).mean()]
    ax.bar([0, 1], np.array(proportions) * 100, color=[BLUE, TEAL], width=0.55)
    ax.set_xticks([0, 1], ["簡化模型", "OpenGATE"])
    ax.set_ylim(0, 112)
    for i, value in enumerate(proportions):
        ax.text(i, value * 100 + 2, f"{value:.3%}", ha="center")
    panel(ax, "同事件比例：分母是所有輸出 pairs", ylabel="同事件 pair 比例 (%)")
    save(
        fig,
        "09_pair_composition",
        "配對 truth 關係與 TOF 檢查",
        "只有 synthetic 的二光子理想模型能把同事件配對直接稱為真配對。GATE 同事件比例為 100%，僅代表此次選取結果；多晶體散射仍可能在同事件內產生多筆 Singles，不能宣稱實機 precision 100%。",
        ["outputs/synthetic/coincidences_ror.csv", "outputs/gate/coincidences_ror.csv"],
        details={"synthetic_categories": dict(zip(names, counts, strict=True))},
    )

    ordered = singles["synthetic"].sort_values(["timestamp_ps", "single_id"]).head(100)
    ranks = {int(single): rank for rank, single in enumerate(ordered.single_id)}
    selected = syn[syn.single_id_1.isin(ranks) & syn.single_id_2.isin(ranks)]
    fig, ax = figure("實際資料｜時間排序後的配對鄰接矩陣（前 100 筆 Singles）", figsize=(8, 7))
    for mask, color, name in [
        (selected.same_truth_event.astype(bool), BLUE, "同事件"),
        (~selected.same_truth_event.astype(bool), ORANGE, "不同事件"),
    ]:
        rows = selected.loc[mask]
        ax.scatter(
            rows.single_id_1.map(ranks),
            rows.single_id_2.map(ranks),
            s=29,
            marker="s",
            c=color,
            label=f"{name}：{len(rows)} 對",
        )
    ax.plot([0, 99], [0, 99], ls="--", lw=1, color=GRAY)
    ax.set(xlim=(-2, 101), ylim=(-2, 101), aspect="equal")
    panel(ax, "只畫無序 pair 的一半矩陣，不重複計數", "第一端時間排序索引", "第二端時間排序索引")
    ax.legend(loc="upper left")
    save(
        fig,
        "10_pair_matrix",
        "實際配對的鄰接矩陣",
        "截取完整量測時間排序後最早 100 筆 Singles，僅畫兩端都在此選取內的既有 pairs。此圖不使用 truth 建立配對；truth 顏色為事後評估。本摘錄可能沒有不同事件 pair，不能用摘錄推算全資料 precision。",
        ["outputs/synthetic/singles_arrival_order.csv", "outputs/synthetic/coincidences_ror.csv"],
        details={"selected_singles": 100, "selected_pairs": len(selected)},
    )


def truth_points(frame, source):
    selected = frame.loc[
        frame.same_truth_event.astype(bool) & frame.physical_tof_valid.astype(bool)
    ]
    points = selected[["ror_x_mm", "ror_y_mm", "ror_z_mm"]].to_numpy(float)
    return selected, points, points - np.asarray(source)


def draw_ror(pairs, cfg, meta):
    for kind, source, number, name, cmap in [
        ("synthetic", cfg["source_mm"], 11, "簡化模型", "Blues"),
        ("gate", meta["source"]["position_mm"], 12, "OpenGATE", "BuGn"),
    ]:
        frame = pairs[kind]
        valid = frame.loc[frame.physical_tof_valid.astype(bool)]
        fig, axes = figure(f"實際重建｜{name} 的 ROR 中心投影", ncols=2, figsize=(12, 5.3))
        for ax, (a, b, i, j) in zip(axes, [("x", "y", 0, 1), ("x", "z", 0, 2)], strict=True):
            image = ax.hist2d(
                valid[f"ror_{a}_mm"],
                valid[f"ror_{b}_mm"],
                bins=80,
                range=[[-100, 100]] * 2,
                cmap=cmap,
                norm=colors.LogNorm(vmin=1),
            )
            fig.colorbar(image[3], ax=ax, label="計數 / 2.5 × 2.5 mm²（對數）", shrink=0.85)
            ax.scatter(
                source[i], source[j], marker="+", c=ORANGE, s=180, linewidths=2, label="已知源位置"
            )
            panel(ax, f"{a.upper()}{b.upper()} 投影：所有有效 TOF pairs", f"{a} (mm)", f"{b} (mm)")
            ax.set_aspect("equal")
            ax.legend(loc="upper left")
        save(
            fig,
            f"{number:02d}_{kind}_ror",
            f"{name} ROR 中心的 XY 與 XZ 投影",
            f"由 {len(valid):,} 對物理 TOF 有效的實際事件累積；包括同事件與不同事件，不在此圖偷偷以 truth 篩選。兩圖為各自的 2D 投影，並非完整 MLEM/OSEM 影像。白色代表零計數，顏色採對數以保留尾部。",
            [
                f"outputs/{kind}/coincidences_ror.csv",
                "reports/synthetic_config.json"
                if kind == "synthetic"
                else "reports/gate_metadata.json",
            ],
        )


def draw_errors(pairs, cfg, meta):
    sources = {"synthetic": cfg["source_mm"], "gate": meta["source"]["position_mm"]}
    errors = {kind: truth_points(pairs[kind], source)[2] for kind, source in sources.items()}
    fig, axes = figure(
        "實際資料｜平均位置接近真值，不代表每個事件都很精準", ncols=2, figsize=(12, 5.3)
    )
    for kind, color, name in [("synthetic", BLUE, "簡化模型"), ("gate", TEAL, "OpenGATE")]:
        distance = np.linalg.norm(errors[kind], axis=1)
        rmse = np.sqrt(np.mean(distance**2))
        axes[0].hist(
            distance,
            bins=np.arange(0, 102, 2),
            density=True,
            histtype="step",
            lw=2,
            color=color,
            label=f"{name}，N={len(distance):,}",
        )
        axes[0].axvline(rmse, c=color, ls="--", lw=1.2)
        axes[1].scatter([kind], [rmse], s=95, color=color, label=f"{name} 單事件 RMSE")
        bias = np.linalg.norm(errors[kind].mean(axis=0))
        axes[1].scatter(
            [kind], [bias], s=90, facecolors="white", edgecolors=color, linewidths=2, marker="D"
        )
        axes[1].text(kind, rmse + 1.1, f"{rmse:.2f} mm", ha="center", color=color)
        axes[1].text(
            kind, bias + 1.1, f"平均偏差 {bias:.3f} mm", ha="center", color=color, fontsize=10
        )
    panel(axes[0], "3D 距離誤差；虛線為 RMSE", "||ROR − source|| (mm)", "機率密度 (1/mm)")
    axes[0].set_xlim(0, 100)
    axes[0].legend()
    panel(axes[1], "實心圓：單事件 RMSE；空心菱形：平均位置誤差", ylabel="誤差 (mm)")
    axes[1].set_xticks([0, 1], ["簡化模型", "OpenGATE"])
    axes[1].set_ylim(0, 21)
    save(
        fig,
        "13_localization_errors",
        "單事件誤差分布與平均位置偏差",
        "只使用同事件且物理 TOF 有效的 pairs。RMSE 取每個事件三維誤差平方的平均再開根號；平均位置偏差先將座標平均再與源位置相減。兩者不可混稱解析度。GATE 同事件不自動代表未散射。",
        ["outputs/synthetic/coincidences_ror.csv", "outputs/gate/coincidences_ror.csv"],
    )

    fig, axes = figure(
        "實際資料｜同一批事件的散布與平均值，使用兩種座標尺度", ncols=2, figsize=(12, 5.4)
    )
    for kind, color, name in [("synthetic", BLUE, "簡化模型"), ("gate", TEAL, "OpenGATE")]:
        error = errors[kind]
        centroid = error.mean(axis=0)
        axes[0].scatter(error[:, 0], error[:, 1], s=4, alpha=0.10, color=color, rasterized=True)
        axes[0].scatter(
            *centroid[:2],
            s=110,
            marker="D",
            edgecolors="white",
            color=color,
            label=f"{name} 平均位置",
        )
        axes[1].scatter(
            *centroid[:2],
            s=130,
            marker="D",
            color=color,
            label=f"{name} ({centroid[0]:+.3f}, {centroid[1]:+.3f}) mm",
        )
        axes[1].annotate(
            name, xy=centroid[:2], xytext=(10, 10), textcoords="offset points", color=color
        )
    for ax in axes:
        ax.axhline(0, c=GRAY, lw=0.8)
        ax.axvline(0, c=GRAY, lw=0.8)
        ax.scatter(0, 0, marker="+", s=140, c=ORANGE, linewidths=2, label="真值原點")
        ax.set_aspect("equal")
    panel(axes[0], "單事件誤差雲：±60 mm", "x − source_x (mm)", "y − source_y (mm)")
    axes[0].set(xlim=(-60, 60), ylim=(-60, 60))
    axes[0].legend(loc="upper left")
    panel(axes[1], "只放大平均位置：±0.65 mm", "平均 x 誤差 (mm)", "平均 y 誤差 (mm)")
    axes[1].set(xlim=(-0.65, 0.65), ylim=(-0.65, 0.65))
    axes[1].legend(loc="upper left", fontsize=9)
    save(
        fig,
        "14_centroid_vs_spread",
        "平均座標與單事件散布的尺度差",
        "左圖畫所有同事件有效 pairs 的 XY 誤差；右圖只放大兩個平均座標，並非另一組實驗，也未聲稱此點為信賴區間。兩張圖刻意使用不同尺度，標題與軸界明確標註。",
        ["outputs/synthetic/coincidences_ror.csv", "outputs/gate/coincidences_ror.csv"],
    )


def draw_sweep(sweep):
    palette = {0: BLUE, 100: ORANGE, 300: PURPLE}
    sigma_palette = {0: BLUE, 40: ORANGE, 80: TEAL, 160: PURPLE}
    fig, ax = figure("實際參數掃描｜隨機時間誤差與固定時鐘偏移都會影響定位", figsize=(10, 5.3))
    for bias, group in sweep.groupby("hemisphere_offset_ps"):
        ax.plot(
            group.timing_sigma_ps,
            group.event_rmse_mm,
            "o-",
            color=palette[bias],
            label=f"半環偏移 {bias} ps",
        )
    zero = sweep[sweep.hemisphere_offset_ps == 0]
    ax.plot(
        zero.timing_sigma_ps, zero.expected_timing_rmse_mm, "--", c=GRAY, label="無偏移解析值 cσ/√2"
    )
    panel(
        ax,
        "每個設定 4,000 個真配對；無背景、100% 偵測效率",
        "每端時間 σ (ps)",
        "單事件三維 RMSE (mm)",
    )
    ax.set_xticks([0, 40, 80, 160])
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper left")
    save(
        fig,
        "15_timing_rmse_sweep",
        "時間抖動與固定偏移對 RMSE 的影響",
        "讀取保存的 12 個掃描設定，不重新模擬。虛線只在半環偏移為 0 時適用。固定偏移改變不同方向 LOR 的位置，不能用增加隨機 σ 完整描述。σ=0 時仍有整數 ps 量化誤差。",
        ["reports/timing_sweep.csv"],
        details={"rows": len(sweep), "events_per_configuration": 4000},
    )

    fig, axes = figure("實際參數掃描｜固定跨半環偏移造成系統性位置偏差", ncols=2, figsize=(12, 5))
    for sigma, group in sweep.groupby("timing_sigma_ps"):
        axes[0].plot(
            group.hemisphere_offset_ps,
            group.centroid_error_mm,
            "o-",
            label=f"每端 σ={sigma} ps",
            color=sigma_palette[sigma],
        )
    panel(axes[0], "平均位置偏差", "x ≥ 0 半環的固定偏移 (ps)", "||mean(ROR) − source|| (mm)")
    axes[0].set_xticks([0, 100, 300])
    axes[0].set_ylim(bottom=0)
    axes[0].legend()
    for bias, group in sweep.groupby("hemisphere_offset_ps"):
        axes[1].plot(
            group.timing_sigma_ps,
            group.centroid_error_mm,
            "o-",
            c=palette[bias],
            label=f"半環偏移 {bias} ps",
        )
    panel(axes[1], "同一組數據改以時間 σ 為橫軸", "每端時間 σ (ps)", "平均位置偏差 (mm)")
    axes[1].set_xticks([0, 40, 80, 160])
    axes[1].set_ylim(bottom=0)
    axes[1].legend()
    save(
        fig,
        "16_clock_bias_sweep",
        "固定時鐘偏移與平均位置偏差",
        "左右圖是同一張 timing_sweep.csv 的兩種切片。每個設定使用相同 seed 與固定方向樣本；曲線是參數情境，不是誤差棒或信賴區間。半環偏移的空間效應依 LOR 方向而變，不能一律換成單一 x 位移。",
        ["reports/timing_sweep.csv"],
    )


def draw_volume(volume, cfg):
    counts = volume["counts"]
    edges = [volume[f"{a}_edges_mm"] for a in "xyz"]
    centers = [(edge[:-1] + edge[1:]) / 2 for edge in edges]
    source = cfg["source_mm"]
    indices = [
        int(np.argmin(np.abs(center - coordinate)))
        for center, coordinate in zip(centers, source, strict=True)
    ]
    fig, axes = figure("實際體素｜64³ ROR 中心計數的投影與切片", ncols=3, figsize=(14.5, 4.8))
    matrices = [counts.sum(axis=2).T, counts[:, :, indices[2]].T, counts[:, indices[1], :].T]
    titles = [
        "XY：沿 z 加總",
        f"XY：z≈{centers[2][indices[2]]:.2f} mm 切片",
        f"XZ：y≈{centers[1][indices[1]]:.2f} mm 切片",
    ]
    coords = [(0, 1), (0, 1), (0, 2)]
    vmax = max(float(matrix.max()) for matrix in matrices)
    for ax, matrix, title, (i, j) in zip(axes, matrices, titles, coords, strict=True):
        image = ax.imshow(
            matrix, origin="lower", extent=[-100, 100, -100, 100], cmap="Blues", vmin=0, vmax=vmax
        )
        ax.scatter(source[i], source[j], marker="+", c=ORANGE, s=100)
        panel(ax, title, f"{'xyz'[i]} (mm)", f"{'xyz'[j]} (mm)")
    fig.colorbar(image, ax=list(axes), label="每格計數（共用線性尺度）", shrink=0.85)
    save(
        fig,
        "17_voxel_slices",
        "ROR 體素計數：投影和切片的差別",
        "直接讀取已產生的 ror_volume.npz。每軸 −100 至 +100 mm、64 bins，體素邊長 3.125 mm。投影把整個軸加總；切片只保留一層，因此計數量級不同。三圖共用相同顏色尺度，避免將各圖自動拉伸後誤認為相同強度。",
        ["outputs/synthetic/ror_volume.npz", "reports/synthetic_config.json"],
        details={
            "shape": list(counts.shape),
            "counts": int(counts.sum()),
            "slice_indices_xyz": indices,
        },
    )


def draw_kernel_precision():
    fig, axes = figure(
        "解析示意｜CTR、單端時間 σ 與沿 LOR 的位置不確定度", ncols=2, figsize=(12, 5.2)
    )
    x = np.linspace(-100, 100, 1000)
    for sigma, color in [(40, TEAL), (80, BLUE), (160, ORANGE)]:
        spatial = C * sigma / np.sqrt(2)
        density = np.exp(-0.5 * (x / spatial) ** 2) / (np.sqrt(2 * np.pi) * spatial)
        axes[0].plot(x, density, c=color, label=f"每端 σ={sigma} ps → σ位置={spatial:.2f} mm")
    panel(
        axes[0],
        "示意 Gaussian ROR 核；目前程式尚未沿線展開此核",
        "沿 LOR 相對中心的位置 (mm)",
        "解析機率密度 (1/mm)",
    )
    axes[0].legend(fontsize=9)
    ctr = np.linspace(0, 500, 100)
    axes[1].plot(ctr, C * ctr / 2, c=BLUE, label="位置 FWHM = c × CTR FWHM / 2")
    for value, color in [(200, TEAL), (2 * np.sqrt(2 * np.log(2)) * np.sqrt(2) * 80, ORANGE)]:
        axes[1].scatter(value, C * value / 2, s=70, c=color)
        axes[1].annotate(
            f"{value:.1f} ps → {C * value / 2:.1f} mm",
            xy=(value, C * value / 2),
            xytext=(10, -20),
            textcoords="offset points",
            fontsize=10,
            color=color,
        )
    panel(axes[1], "兩端差值 CTR 與位置 FWHM 的換算", "CTR FWHM (ps)", "沿 LOR 的位置 FWHM (mm)")
    axes[1].set(xlim=(0, 500), ylim=(0, 85))
    axes[1].legend(loc="upper left", fontsize=9)
    save(
        fig,
        "18_ctr_uncertainty",
        "時間解析度與 ROR 不確定度的解析關係",
        "純解析示意，未拿 Gaussian 曲線冒充實驗分布。假設兩端獨立同 σ 的 Gaussian 誤差，σdt=√2σ，σ位置=cσ/√2。此版軟體只重建每個事件的 ROR 中心，有限寬度核是下一步。",
        ["src/pet_sim/config.py", "src/pet_sim/reconstruction.py"],
        "analytical_illustration",
    )

    fig, axes = figure("精度示意｜時間先做整數差，再換成距離", ncols=2, figsize=(12, 5))
    exponents = np.arange(9, 20)
    magnitudes = np.power(10.0, exponents)
    spacing = np.spacing(magnitudes)
    axes[0].loglog(magnitudes, spacing, "o-", c=ORANGE, label="float64 相鄰可表示值的距離")
    axes[0].axhline(1, c=BLUE, ls="--", label="1 ps")
    axes[0].axvline(2**53, c=GRAY, ls=":", label="2^53：所有整數精確表示的界線")
    panel(axes[0], "以 ps 作為儲存數值單位", "時間戳數值大小 (ps)", "相鄰 float64 數值間隔 (ps)")
    axes[0].legend(fontsize=9, loc="upper left")
    ax = axes[1]
    ax.axis("off")
    ax.text(0.04, 0.91, "同一對時間戳：", fontsize=13, transform=ax.transAxes)
    entries = [
        ("t1", str(2**60 + 1)),
        ("t2", str(2**60 + 2)),
        ("int64 先相減", "dt = 1 ps"),
        ("先轉 float64 再相減", "dt = 0 ps（資訊已遺失）"),
    ]
    for index, (label, text) in enumerate(entries):
        y = 0.72 - index * 0.19
        ax.text(
            0.04,
            y,
            label,
            transform=ax.transAxes,
            color=BLUE if index == 2 else ORANGE if index == 3 else GRAY,
            fontsize=11,
        )
        ax.text(0.04, y - 0.07, text, transform=ax.transAxes, fontsize=12)
    save(
        fig,
        "19_timestamp_precision",
        "int64 ps 時間戳與浮點精度",
        "數值精度示意，不是本次 acquisition 的時間跨度。圖中演算直接使用 IEEE-754 float64 的 spacing。ROOT 匯入先減共同原點並明訂單位；若來源本已浮點化而遺失時間差，之後轉成 int64 也無法恢復。",
        ["src/pet_sim/root_io.py", "src/pet_sim/reconstruction.py"],
        "numerical_illustration",
    )


def draw_counts(singles, pairs, meta, metrics, cfg):
    fig, axes = figure(
        "實際計數｜每個階段的觀測單位不同，不能直接當成效率漏斗", ncols=2, figsize=(12, 5.3)
    )
    syn_counts = [
        cfg["simulation"]["n_events"],
        len(singles["synthetic"]),
        len(pairs["synthetic"]),
        int(pairs["synthetic"].same_truth_event.astype(bool).sum()),
        int(metrics["histogram_counts_inside_100mm_cube"]),
    ]
    syn_labels = [
        "接受後湮滅事件",
        "偵測 Singles + 背景",
        "符合 pairs",
        "其中真配對",
        "體素範圍內有效 pairs",
    ]
    gate_counts = [
        meta["actual_generated_events"],
        meta["root_inspection"]["Hits"]["entries"],
        len(singles["gate"]),
        len(pairs["gate"]),
    ]
    gate_labels = ["生成湮滅事件", "Geant4 Hits", "Digitizer Singles", "符合 pairs"]
    for ax, counts, labels, color, title in [
        (axes[0], syn_counts, syn_labels, BLUE, "簡化模型"),
        (axes[1], gate_counts, gate_labels, TEAL, "OpenGATE"),
    ]:
        positions = np.arange(len(counts))
        ax.barh(positions, counts, color=color, alpha=0.88)
        for i, count in enumerate(counts):
            ax.text(count + max(counts) * 0.02, i, f"{count:,}", va="center", fontsize=10)
        ax.set_yticks(positions, labels)
        ax.invert_yaxis()
        ax.set_xlim(0, max(counts) * 1.28)
        panel(ax, title, "各階段筆數（類型不同）")
    save(
        fig,
        "20_stage_counts",
        "兩條流程各階段的實際計數",
        "事件、Hits、Singles、pairs 與體素中的有效 pairs 是不同觀測單位。GATE 一個光子可留下多個能量沉積 Hits；synthetic n_events 已條件於幾何接受，且含獨立背景。因此這張圖刻意使用分開的橫條比較，不能把相鄰條直接相除當成掃描器靈敏度。",
        [
            "reports/synthetic_config.json",
            "reports/gate_metadata.json",
            "outputs/synthetic/singles_arrival_order.csv",
            "outputs/gate/singles_arrival_order.csv",
            "outputs/synthetic/coincidences_ror.csv",
            "outputs/gate/coincidences_ror.csv",
            "reports/synthetic_metrics.json",
        ],
        details={
            "synthetic_counts": dict(zip(syn_labels, syn_counts, strict=True)),
            "gate_counts": dict(zip(gate_labels, gate_counts, strict=True)),
        },
    )


def main():
    style = configure_style()
    cfg, meta, sm, gm, singles, pairs, sweep, volume = sources_and_frames()
    draw_pipeline()
    draw_geometry(cfg, meta)
    draw_tof()
    draw_stream(singles)
    draw_energy_dt(singles, pairs, cfg)
    draw_pair_structure(pairs, singles)
    draw_ror(pairs, cfg, meta)
    draw_errors(pairs, cfg, meta)
    draw_sweep(sweep)
    draw_volume(volume, cfg)
    draw_kernel_precision()
    draw_counts(singles, pairs, meta, sm, cfg)
    for relative in sorted({source for entry in FIGURES for source in entry["sources"]}):
        if relative not in INPUTS:
            tracked(relative)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(
        subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    )
    manifest = {
        "created_at": datetime.now(ZoneInfo("Asia/Taipei")).isoformat(),
        "renderer": "matplotlib; standard static scientific figures; no new simulations",
        "font": style,
        "theme": "light",
        "dpi": 150,
        "git_revision_at_render": revision,
        "git_dirty_at_render": dirty,
        "generator": str(Path(__file__).relative_to(ROOT)),
        "generator_sha256": digest(__file__),
        "versions": {name: version(name) for name in ("numpy", "pandas", "matplotlib")},
        "evidence_revisions": {
            kind: json.loads((ROOT / f"outputs/{kind}/manifest.json").read_text())["git_revision"]
            for kind in ("synthetic", "gate")
        },
        "inputs": INPUTS,
        "figures": FIGURES,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 縮圖僅供版面 QA，正式圖仍使用各自的 150 dpi PNG／SVG。
    for sheet in range(2):
        canvas = Image.new("RGB", (1600, 1850), "white")
        draw = ImageDraw.Draw(canvas)
        for index, entry in enumerate(FIGURES[sheet * 10 : (sheet + 1) * 10]):
            thumbnail = ImageOps.contain(Image.open(OUT / entry["png"]).convert("RGB"), (790, 345))
            x = (index % 2) * 800 + (800 - thumbnail.width) // 2
            y = (index // 2) * 370 + 25
            canvas.paste(thumbnail, (x, y))
            draw.text(((index % 2) * 800 + 12, (index // 2) * 370 + 6), entry["id"], fill=INK)
        canvas.save(OUT / f"qa_contact_sheet_{sheet + 1}.png")
    print(
        json.dumps(
            {"figures": len(FIGURES), "output": str(OUT), "font": style["family"]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
