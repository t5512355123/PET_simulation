"""命令列入口：模擬、匯入、重建、驗證與時間同步誤差掃描。"""

import argparse
from dataclasses import replace
import json
from pathlib import Path

import pandas as pd

from .config import CoincidenceConfig, SimulationConfig
from .pipeline import run_pipeline, write_json
from .root_io import inspect_root, load_gate_singles
from .simulation import simulate_singles
from .validation import run_sweep, validate_software


def main(argv=None):
    parser = argparse.ArgumentParser(description="PET Singles → Coincidence → TOF-ROR 驗證")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="建立簡化模擬並執行完整流程")
    demo.add_argument("--out", default="outputs/synthetic")
    demo.add_argument("--events", type=int, default=8000)
    demo.add_argument("--seed", type=int, default=20261019)
    demo.add_argument("--timing-sigma-ps", type=float, default=80)
    demo.add_argument("--hemisphere-offset-ps", type=int, default=0)
    demo.add_argument("--config", type=Path, help="SimulationConfig JSON，可覆寫所有模擬參數")
    run = sub.add_parser("run", help="讀取統一格式 Singles CSV 並重建")
    run.add_argument("input", type=Path)
    run.add_argument("--out", default="outputs/imported")
    run.add_argument("--source-mm", type=float, nargs=3)
    for p in (demo, run):
        p.add_argument("--window-ps", type=int, default=4000)
        p.add_argument("--energy-kev", type=float, nargs=2, default=(350, 650))
        p.add_argument("--min-angle-deg", type=float, default=120)
    inspect = sub.add_parser("inspect-root", help="列出 ROOT trees 與 branches，不猜格式")
    inspect.add_argument("input", type=Path)
    imp = sub.add_parser("import-root", help="依明確 mapping 將 ROOT Singles 轉成 CSV")
    imp.add_argument("input", type=Path)
    imp.add_argument("--tree", required=True)
    imp.add_argument("--mapping", required=True, type=Path)
    imp.add_argument("--out", required=True, type=Path)
    imp.add_argument("--entry-stop", type=int)
    valid = sub.add_parser("validate", help="獨立 oracle、無雜訊與解析誤差驗證")
    valid.add_argument("--out", default="outputs/validation.json", type=Path)
    sweep = sub.add_parser("sweep", help="掃描時間抖動與跨半環時鐘偏移")
    sweep.add_argument("--out", default="outputs/timing_sweep.csv", type=Path)
    args = parser.parse_args(argv)
    if args.command == "inspect-root":
        result = inspect_root(args.input)
    elif args.command == "import-root":
        mapping = json.loads(args.mapping.read_text(encoding="utf-8-sig"))
        frame = load_gate_singles(args.input, args.tree, mapping, args.entry_stop)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(args.out, index=False)
        write_json(args.out.with_suffix(".provenance.json"), frame.attrs)
        result = {"singles": len(frame), "output": str(args.out)}
    elif args.command == "validate":
        result = validate_software()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.out, result)
    elif args.command == "sweep":
        print(run_sweep(args.out).to_string(index=False))
        return
    else:
        if args.command == "demo":
            if args.config:
                cfg = SimulationConfig(**json.loads(args.config.read_text(encoding="utf-8-sig")))
            else:
                cfg = replace(SimulationConfig(), n_events=args.events, seed=args.seed,
                              timing_sigma_ps=args.timing_sigma_ps,
                              hemisphere_offset_ps=args.hemisphere_offset_ps)
            frame = simulate_singles(cfg)
            source = cfg.source_mm
        else:
            cfg = None
            frame = pd.read_csv(args.input)
            provenance = args.input.with_suffix(".provenance.json")
            if provenance.exists():
                frame.attrs.update(json.loads(provenance.read_text(encoding="utf-8-sig")))
            source = args.source_mm
        cuts = CoincidenceConfig(args.window_ps, *args.energy_kev, args.min_angle_deg)
        result = run_pipeline(frame, args.out, cuts,
            "synthetic" if cfg else "imported", source, cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
