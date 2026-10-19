"""串接模組並記錄參數、版本與輸出雜湊，讓每次實驗可追溯。"""

import hashlib
import json
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

import numpy as np

from .coincidence import find_coincidences, validate_singles
from .config import CoincidenceConfig
from .metrics import summarize
from .plotting import save_ror_plot
from .reconstruction import histogram_ror, reconstruct_ror


def write_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )


def file_sha256(path):
    """分塊計算輸入雜湊，不另外把整個大型 CSV 載入記憶體。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_pipeline(
    singles,
    output_dir,
    coincidence_config=None,
    dataset_kind="imported",
    source_mm=None,
    simulation_config=None,
):
    start = time.perf_counter()
    coincidence_config = (
        coincidence_config if coincidence_config is not None else CoincidenceConfig()
    )
    frame = validate_singles(singles)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    pairs = find_coincidences(frame, coincidence_config)
    ror = reconstruct_ror(pairs)
    metrics = summarize(frame, ror, dataset_kind, source_mm)
    volume, edges = histogram_ror(
        ror.loc[ror.physical_tof_valid.astype(bool)], bins=64, extent_mm=100
    )
    metrics["histogram_counts_inside_100mm_cube"] = int(volume.sum())
    metrics["histogram_valid_pairs_outside_cube"] = metrics["physical_tof_valid_pairs"] - int(
        volume.sum()
    )
    frame.to_csv(out / "singles_arrival_order.csv", index=False)
    ror.to_csv(out / "coincidences_ror.csv", index=False)
    np.savez_compressed(
        out / "ror_volume.npz",
        counts=volume,
        x_edges_mm=edges[0],
        y_edges_mm=edges[1],
        z_edges_mm=edges[2],
    )
    save_ror_plot(ror, out / "ror_projections.png", source_mm)
    write_json(out / "metrics.json", metrics)
    settings = {
        "coincidence": asdict(coincidence_config),
        "simulation": simulation_config.to_dict() if simulation_config else None,
        "source_mm": source_mm,
        "import_provenance": singles.attrs.get("provenance"),
        "input_csv": singles.attrs.get("input_csv"),
    }
    write_json(out / "config.json", settings)
    try:
        project = Path(__file__).resolve().parents[2]
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=project, stderr=subprocess.DEVNULL, text=True
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=project, stderr=subprocess.DEVNULL, text=True
            ).strip()
        )
    except (subprocess.SubprocessError, OSError):
        revision = None
        dirty = None
    files = [p for p in out.iterdir() if p.is_file() and p.name != "manifest.json"]
    manifest = {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "git_revision": revision,
        "git_dirty": dirty,
        "source_sha256": {
            p.name: file_sha256(p) for p in sorted(Path(__file__).resolve().parent.glob("*.py"))
        },
        "dependencies": {p: version(p) for p in ("numpy", "pandas", "matplotlib", "uproot")},
        "elapsed_seconds": time.perf_counter() - start,
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)},
    }
    write_json(out / "manifest.json", manifest)
    return metrics
