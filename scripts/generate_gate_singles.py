"""以真正的 OpenGATE / Geant4 產生尚未做 coincidence 配對的 PET Singles。

這是簡化的物理模擬案例：96 個 BGO 晶體、偏心點光源、背對背 511 keV
光子。先保存 Hits，再以 adder 產生 SinglesIdeal，最後加入獨立的單通道
時間誤差，輸出 Singles。請勿將它解讀為實機或完整電子學模型。
"""

from __future__ import annotations

import argparse
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform
from typing import Any


def parse_args() -> argparse.Namespace:
    """讀取生成設定；事件數是 Poisson 流的期望值，不是固定筆數。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/raw/gate_demo"))
    parser.add_argument("--expected-events", type=int, default=30000)
    parser.add_argument("--activity-bq", type=float, default=200000.0)
    parser.add_argument("--source-mm", type=float, nargs=3, default=[30.0, -15.0, 10.0])
    parser.add_argument("--ctr-ps", type=float, default=200.0)
    parser.add_argument("--seed", type=int, default=20261019)
    parser.add_argument("--dry-run", action="store_true", help="只列出設定，不匯入或執行 Geant4")
    args = parser.parse_args()
    if args.expected_events <= 0 or not math.isfinite(args.activity_bq) or args.activity_bq <= 0:
        parser.error("expected-events 與 activity-bq 必須大於 0")
    if not math.isfinite(args.ctr_ps) or args.ctr_ps < 0:
        parser.error("ctr-ps 必須是非負有限值")
    if not all(math.isfinite(v) for v in args.source_mm):
        parser.error("source-mm 必須是有限值")
    if math.hypot(*args.source_mm[:2]) >= 150 or abs(args.source_mm[2]) >= 40:
        parser.error("點光源必須位於半徑 150 mm、|z| < 40 mm 的示範 FOV 中")
    return args


def describe(args: argparse.Namespace) -> dict[str, Any]:
    """保存幾何、單位與限制，讓 ROOT 資料可以追溯到模擬設定。"""
    return {
        "generator": "OpenGATE / Geant4 electromagnetic transport",
        "python": platform.python_version(),
        "expected_events": args.expected_events,
        "activity_bq": args.activity_bq,
        "duration_s": args.expected_events / args.activity_bq,
        "seed": args.seed,
        "number_of_threads": 1,
        "source": {
            "particle": "back_to_back",
            "photon_energy_kev": 511.0,
            "position_mm": args.source_mm,
            "angular_distribution": "isotropic 3D",
            "accolinearity": False,
        },
        "detector": {
            "material": "BGO",
            "crystals": 96,
            "center_radius_mm": 200.0,
            "crystal_size_radial_tangential_axial_mm": [20.0, 10.0, 100.0],
        },
        "root_file": "singles.root",
        "trees": {"Hits": "Geant4 能量沉積", "SinglesIdeal": "逐事件逐晶體 adder", "Singles": "加上時間誤差的未配對 Singles"},
        "root_units": {"GlobalTime": "ns", "TotalEnergyDeposit": "MeV", "PostPosition_X/Y/Z": "mm"},
        "coincidence_timing_fwhm_ps": args.ctr_ps,
        "single_channel_timing_fwhm_ps": args.ctr_ps / math.sqrt(2),
        "limitations": [
            "光子傳輸使用 Geant4；光源直接產生背對背光子，未模擬正電子飛行與衰變。",
            "晶體位置使用能量加權互動座標，未模擬完整實機讀出與 DOI 誤差。",
            "無受測物、衰減修正、隨機修正、死時間或能量解析度模型。",
            "CTR 是兩個獨立單通道時間誤差的差值 FWHM；單通道 FWHM = CTR / sqrt(2)。",
            "EventID / RunID 僅供事後真值評估，不能用來建立 coincidence。",
        ],
    }


def build_simulation(args: argparse.Namespace) -> Any:
    """用官方測試相同的 GenericSource、Hits、Adder 和 Blurring API 建模。"""
    try:
        import opengate as gate
    except ImportError as exc:
        raise SystemExit("請在 pet-simulation 環境安裝：python -m pip install opengate==10.1.1") from exc

    mm, sec = gate.g4_units.mm, gate.g4_units.s
    sim = gate.Simulation()
    sim.number_of_threads = 1
    sim.random_seed = args.seed
    sim.visu = False
    sim.g4_verbose = False
    sim.check_volumes_overlap = True
    sim.output_dir = args.output.resolve()
    sim.world.size = [600 * mm, 600 * mm, 300 * mm]
    sim.world.material = "G4_AIR"

    # 材料以化學計量與密度明確定義，避免外部 GateMaterials 資料庫相依。
    sim.volume_manager.material_database.add_material_nb_atoms(
        "BGO", ["Bi", "Ge", "O"], [4, 3, 12], 7.13 * gate.g4_units.g_cm3
    )
    crystal = sim.add_volume("Box", "crystal")
    crystal.size = [20 * mm, 10 * mm, 100 * mm]
    crystal.material = "BGO"
    translations, rotations = gate.geometry.utility.get_circular_repetition(
        96, [200 * mm, 0, 0], start_angle_deg=0, axis=[0, 0, 1]
    )
    crystal.translation = translations
    crystal.rotation = rotations

    # 必須用 activity 產生分散在時間軸上的 Poisson 到達事件。
    # 固定 number_of_primaries 模式會把事件放在相同生成時間，不適合測 coincidence。
    source = sim.add_source("GenericSource", "annihilation_point")
    source.particle = "back_to_back"
    source.activity = args.activity_bq * gate.g4_units.Bq
    source.position.type = "point"
    source.position.translation = [v * mm for v in args.source_mm]
    source.direction.type = "iso"
    source.direction.accolinearity_flag = False
    source.energy.mono = 511 * gate.g4_units.keV
    sim.run_timing_intervals = [[0, args.expected_events / args.activity_bq * sec]]

    sim.physics_manager.physics_list_name = "G4EmStandardPhysics_option4"
    sim.physics_manager.set_production_cut("world", "all", 0.1 * mm)

    # ROOT 會保留多重散射與跨晶體事件，而不是先以真值挑出「正確配對」。
    hits = sim.add_actor("DigitizerHitsCollectionActor", "Hits")
    hits.attached_to = crystal.name
    hits.authorize_repeated_volumes = True
    hits.output_filename = "singles.root"
    hits.attributes = [
        "EventID", "RunID", "ThreadID", "PostPosition", "TotalEnergyDeposit",
        "PreStepUniqueVolumeID", "GlobalTime", "EventPosition",
    ]
    adder = sim.add_actor("DigitizerAdderActor", "SinglesIdeal")
    adder.attached_to = crystal.name
    adder.authorize_repeated_volumes = True
    adder.input_digi_collection = hits.name
    adder.policy = "EnergyWeightedCentroidPosition"
    adder.output_filename = "singles.root"

    singles = sim.add_actor("DigitizerBlurringActor", "Singles")
    singles.attached_to = crystal.name
    singles.authorize_repeated_volumes = True
    singles.input_digi_collection = adder.name
    singles.blur_attribute = "GlobalTime"
    singles.blur_method = "Gaussian"
    singles.blur_fwhm = args.ctr_ps / math.sqrt(2) * gate.g4_units.ps
    singles.output_filename = "singles.root"
    stats = sim.add_actor("SimulationStatisticsActor", "Stats")
    stats.track_types_flag = True
    return sim


def inspect_root(path: Path) -> dict[str, Any]:
    """執行後直接重新讀取 ROOT，確認關鍵欄位與未配對資料存在。"""
    import numpy as np
    import uproot

    with uproot.open(path) as root:
        summary = {}
        for name in ["Hits", "SinglesIdeal", "Singles"]:
            tree = root[name]
            needed = ["GlobalTime", "TotalEnergyDeposit", "PostPosition_X", "PostPosition_Y", "PostPosition_Z", "EventID", "RunID", "PreStepUniqueVolumeID"]
            missing = set(needed) - set(tree.keys())
            if missing:
                raise RuntimeError(f"{name} 缺少必要欄位：{sorted(missing)}")
            arrays = tree.arrays(["GlobalTime", "TotalEnergyDeposit"], library="np")
            if len(arrays["GlobalTime"]) == 0:
                raise RuntimeError(f"{name} 沒有資料；請提高 expected-events")
            if not all(np.all(np.isfinite(v)) for v in arrays.values()):
                raise RuntimeError(f"{name} 包含非有限數值")
            summary[name] = {
                "entries": tree.num_entries,
                "branches": list(tree.keys()),
                "time_range_ns": [float(arrays["GlobalTime"].min()), float(arrays["GlobalTime"].max())],
                "energy_range_mev": [float(arrays["TotalEnergyDeposit"].min()), float(arrays["TotalEnergyDeposit"].max())],
            }
    return summary


def import_mapping() -> dict[str, Any]:
    """建立本例專用明確單位映射；字串 volume ID 由匯入器保存編碼表。"""
    return {
        "time_unit": "ns",
        "position_unit": "mm",
        "energy_unit": "MeV",
        "time_origin": 0,
        "detector_id_encoding": "categorical",
        "fields": {
            "timestamp_ps": "GlobalTime",
            "detector_id": "PreStepUniqueVolumeID",
            "energy_kev": "TotalEnergyDeposit",
            "x_mm": "PostPosition_X",
            "y_mm": "PostPosition_Y",
            "z_mm": "PostPosition_Z",
            "truth_event_id": "EventID",
            "truth_run_id": "RunID",
            "truth_source_x_mm": "EventPosition_X",
            "truth_source_y_mm": "EventPosition_Y",
            "truth_source_z_mm": "EventPosition_Z",
        },
    }


def main() -> None:
    args = parse_args()
    metadata = describe(args)
    if args.dry_run:
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return
    if (args.output / "singles.root").exists():
        raise SystemExit("輸出 singles.root 已存在；請指定新的 --output 資料夾以保留原始資料。")
    args.output.mkdir(parents=True, exist_ok=True)
    metadata["opengate_version"] = version("opengate")
    sim = build_simulation(args)
    # Windows multiprocessing 必須放在 main 保護之下；本例使用單執行緒確保可重現。
    sim.run()
    metadata["actual_generated_events"] = int(sim.get_actor("Stats").counts.events)
    metadata["root_inspection"] = inspect_root(args.output / "singles.root")
    (args.output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "mapping.json").write_text(json.dumps(import_mapping(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "actual_generated_events": metadata["actual_generated_events"], "singles": metadata["root_inspection"]["Singles"]["entries"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
