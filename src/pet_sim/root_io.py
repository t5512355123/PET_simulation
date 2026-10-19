"""以明確分支與單位映射匯入 ROOT Singles；不推測儀器或 GATE 版本。"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from pathlib import Path

import numpy as np
import pandas as pd
import uproot


REQUIRED_FIELDS = (
    "timestamp_ps", "detector_id", "x_mm", "y_mm", "z_mm", "energy_kev",
)
OPTIONAL_FIELDS = (
    "truth_event_id", "truth_run_id",
    "truth_source_x_mm", "truth_source_y_mm", "truth_source_z_mm",
)
TIME_FACTORS = {"s": 1_000_000_000_000, "ns": 1_000, "ps": 1}
POSITION_FACTORS = {"mm": 1.0, "cm": 10.0, "m": 1_000.0}
ENERGY_FACTORS = {"MeV": 1_000.0, "keV": 1.0}
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


def inspect_root(path) -> dict:
    """列出 TTree/RNTuple、筆數與分支；不假定資料樹必須稱為 Singles。"""
    trees = []
    with uproot.open(path) as root_file:
        for name, class_name in root_file.classnames(recursive=True, cycle=False).items():
            if not (class_name.startswith("TTree") or "RNTuple" in class_name):
                continue
            tree = root_file[name]
            branches = list(tree.keys())
            trees.append({
                "name": name,
                "class_name": class_name,
                "num_entries": int(tree.num_entries),
                "branches": branches,
                "branch_types": {
                    branch: str(getattr(tree[branch], "typename", "unknown"))
                    for branch in branches
                },
            })
    return {"path": str(Path(path).resolve()), "trees": trees}


def _decimal(value, name: str) -> Decimal:
    """保留整數與字串精度，避免先轉為 float64 破壞大型時間戳記。"""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} 不接受布林值")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} 必須為有限數值") from exc
    if not result.is_finite():
        raise ValueError(f"{name} 必須為有限數值")
    return result


def _integer_array(values: np.ndarray, name: str) -> np.ndarray:
    """明確檢查整數性與 int64 範圍，不以 astype 靜默截斷或溢位。"""
    result = np.empty(len(values), dtype=np.int64)
    for i, value in enumerate(values):
        number = _decimal(value, name)
        if number != number.to_integral_value():
            raise ValueError(f"{name} 第 {i} 筆不是整數")
        if not INT64_MIN <= number <= INT64_MAX:
            raise ValueError(f"{name} 第 {i} 筆超出 int64 範圍")
        result[i] = int(number)
    return result


def _categorical_detectors(values: np.ndarray) -> tuple[np.ndarray, dict]:
    """以字典序編碼全域偵測器字串標籤，並保留可追溯的對照表。"""
    labels = []
    for value in values:
        if isinstance(value, (bytes, np.bytes_)):
            try:
                label = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("detector_id 標籤必須是 UTF-8 字串") from exc
        elif isinstance(value, (str, np.str_)):
            label = str(value)
        else:
            raise ValueError("categorical detector_id 只接受字串標籤")
        if not label.strip():
            raise ValueError("detector_id 標籤不可為空字串")
        labels.append(label)
    label_map = {label: i for i, label in enumerate(sorted(set(labels)))}
    return np.asarray([label_map[label] for label in labels], dtype=np.int64), label_map


def _timestamps(values: np.ndarray, factor: int, origin: Decimal) -> np.ndarray:
    """先減明訂原點，再轉 ps；四捨六入五成雙，結果必須落在 int64。"""
    result = np.empty(len(values), dtype=np.int64)
    # 輸入可以是整數或十進位字串；64 位時間戳記換算最多約 32 位有效數字。
    with localcontext() as context:
        context.prec = 80
        for i, value in enumerate(values):
            time_ps = ((_decimal(value, "timestamp_ps") - origin) * factor).to_integral_value(
                rounding=ROUND_HALF_EVEN
            )
            if not INT64_MIN <= time_ps <= INT64_MAX:
                raise ValueError(
                    f"timestamp_ps 第 {i} 筆換算後超出 int64；"
                    "請以輸入時間單位明訂 time_origin"
                )
            result[i] = int(time_ps)
    return result


def _finite_array(values: np.ndarray, name: str, factor: float) -> np.ndarray:
    """檢查空值、非有限值以及換算溢位；距離與能量採 float64。"""
    try:
        with np.errstate(over="ignore", invalid="ignore"):
            result = values.astype(np.float64) * factor
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{name} 必須為有限數值") from exc
    if not np.isfinite(result).all():
        raise ValueError(f"{name} 含非有限值或換算後溢位")
    return result


def _validate_mapping(mapping: dict) -> tuple[dict, Decimal]:
    if not isinstance(mapping, dict) or not isinstance(mapping.get("fields"), dict):
        raise ValueError("映射必須包含 fields 物件與三種明確單位")
    fields = mapping["fields"]
    if any(not isinstance(field, str) for field in fields):
        raise ValueError("fields 中標準欄位名稱必須為字串")
    missing = [field for field in REQUIRED_FIELDS if field not in fields]
    if missing:
        raise ValueError(f"缺少必要 Singles 欄位映射：{', '.join(missing)}")
    unknown = sorted(set(fields) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS))
    if unknown:
        raise ValueError(f"不支援的欄位映射：{', '.join(unknown)}")
    if any(not isinstance(branch, str) or not branch.strip() for branch in fields.values()):
        raise ValueError("fields 中每個分支名稱都必須為非空字串")
    for key, factors in (
        ("time_unit", TIME_FACTORS),
        ("position_unit", POSITION_FACTORS),
        ("energy_unit", ENERGY_FACTORS),
    ):
        if not isinstance(mapping.get(key), str) or mapping[key] not in factors:
            raise ValueError(f"{key} 必須明訂為 {'/'.join(factors)}")
    truth_positions = [field in fields for field in OPTIONAL_FIELDS[2:]]
    if any(truth_positions) and not all(truth_positions):
        raise ValueError("truth_source_x_mm/y_mm/z_mm 必須同時映射")
    if mapping.get("detector_id_encoding", "integer") not in ("integer", "categorical"):
        raise ValueError("detector_id_encoding 必須為 integer 或 categorical")
    return fields, _decimal(mapping.get("time_origin", 0), "time_origin")


def load_gate_singles(
    path, tree: str, mapping: dict, entry_stop: int | None = None
) -> pd.DataFrame:
    """將已確認語意的 ROOT 單事件樹轉為標準 Singles DataFrame。

    ``mapping`` 的 ``fields`` 對應標準名稱與 ROOT 分支，並須指定
    ``time_unit`` (s/ns/ps)、``position_unit`` (mm/cm/m)、``energy_unit`` (MeV/keV)。
    ``time_origin`` 可用輸入時間單位指定共同原點，建議大型絕對時間使用字串。
    時間轉換不會先將整數轉為 float64；若來源已是浮點數，其遺失精度無法復原。
    原點為共同平移，因此不改變單一檔案內的時間差。

    複合偵測器字串標籤可明訂 ``detector_id_encoding='categorical'``，以本次
    載入範圍內的字典序編碼並保留對照表。跨檔案或不同 ``entry_stop`` 合併前
    必須依對照表重新編碼；預設 ``integer`` 不自動編碼非數值標籤。

    ``arrival_time_ps`` 等於量測時間、``lane_id`` 為 0，僅為下游介面佔位；
    它們不是實測接收時間或通道資訊。此限制寫入 ``DataFrame.attrs``。
    truth 欄位均可省略；event ID 僅在同一個檔案內解讀，跨 run 使用時需同時
    映射 ``truth_run_id``。不提供跨檔案事件編號唯一性的保證。
    本函式驗證分支結構，無法自行證明來源已是正確校正的 Singles。
    """
    fields, origin = _validate_mapping(mapping)
    if entry_stop is not None and (
        isinstance(entry_stop, bool) or not isinstance(entry_stop, int) or entry_stop < 0
    ):
        raise ValueError("entry_stop 必須為非負整數或 None")
    with uproot.open(path) as root_file:
        if tree not in root_file:
            raise ValueError(f"ROOT 中找不到資料樹：{tree}")
        root_tree = root_file[tree]
        if not hasattr(root_tree, "arrays") or not hasattr(root_tree, "num_entries"):
            raise ValueError(f"ROOT 物件不是 TTree/RNTuple：{tree}")
        available = set(root_tree.keys())
        missing = sorted(set(fields.values()) - available)
        if missing:
            raise ValueError(
                "缺少映射的 Singles 分支：" + ", ".join(missing)
                + "；若此檔案只有已配對的 Coincidences，無法還原原始 Singles"
            )
        # 使用分支逐一讀取可同時支援 TTree 與 RNTuple，避免 record-array 差異。
        raw = {
            field: np.asarray(root_tree[branch].array(entry_stop=entry_stop, library="np"))
            for field, branch in fields.items()
        }
        entries_in_tree = int(root_tree.num_entries)
    for field, values in raw.items():
        categorical_detector = (
            field == "detector_id" and mapping.get("detector_id_encoding") == "categorical"
        )
        allowed_types = "USO" if categorical_detector else "iufUS"
        if values.ndim != 1 or values.dtype.kind not in allowed_types:
            value_type = "字串" if categorical_detector else "數值"
            raise ValueError(f"{field} 對應分支必須為一維純量{value_type}")
    n_rows = len(raw["timestamp_ps"])
    if any(len(values) != n_rows for values in raw.values()):
        raise ValueError("映射分支長度不一致")
    time_ps = _timestamps(raw["timestamp_ps"], TIME_FACTORS[mapping["time_unit"]], origin)
    detector_encoding = mapping.get("detector_id_encoding", "integer")
    detector_label_map = None
    if detector_encoding == "categorical":
        detector_ids, detector_label_map = _categorical_detectors(raw["detector_id"])
    else:
        detector_ids = _integer_array(raw["detector_id"], "detector_id")
    columns = {
        "single_id": np.arange(n_rows, dtype=np.int64),
        "timestamp_ps": time_ps,
        "detector_id": detector_ids,
    }
    position_factor = POSITION_FACTORS[mapping["position_unit"]]
    for field in ("x_mm", "y_mm", "z_mm"):
        columns[field] = _finite_array(raw[field], field, position_factor)
    columns["energy_kev"] = _finite_array(
        raw["energy_kev"], "energy_kev", ENERGY_FACTORS[mapping["energy_unit"]]
    )
    columns["arrival_time_ps"] = time_ps.copy()
    columns["lane_id"] = np.zeros(n_rows, dtype=np.int64)
    for field in OPTIONAL_FIELDS:
        if field in raw:
            columns[field] = (
                _integer_array(raw[field], field) if field.endswith("_id")
                else _finite_array(raw[field], field, position_factor)
            )
    result = pd.DataFrame(columns)
    result.attrs["provenance"] = {
        "source_file": str(Path(path).resolve()),
        "source_tree": tree,
        "entries_in_tree": entries_in_tree,
        "entries_loaded": n_rows,
        "fields": dict(fields),
        "input_units": {key: mapping[key] for key in (
            "time_unit", "position_unit", "energy_unit"
        )},
        "time_origin_input_unit": str(origin),
        "timestamp_rounding": "ROUND_HALF_EVEN",
        "placeholder_columns": {"arrival_time_ps": "timestamp_ps 的複本", "lane_id": 0},
        "truth_id_scope": "單一 ROOT 檔案；跨 run 請映射 truth_run_id，跨檔案需額外識別碼",
        "source_float_precision": "不會復原來源浮點數已失去的時間精度",
        "detector_id_encoding": detector_encoding,
        "detector_id_label_map": detector_label_map,
        "detector_id_encoding_scope": (
            "單次載入選取範圍；跨檔案或不同 entry_stop 必須依表重編碼"
            if detector_encoding == "categorical" else "來源整數 ID"
        ),
    }
    return result
