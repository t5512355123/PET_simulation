"""以人工建立的 ROOT 結構測試匯入；這些 fixture 並非真實 GATE 掃描資料。"""

import numpy as np
import pytest
import uproot

from pet_sim.root_io import inspect_root, load_gate_singles


@pytest.fixture
def mapping():
    return {
        "fields": {
            "timestamp_ps": "time", "detector_id": "crystalID",
            "x_mm": "globalPosX", "y_mm": "globalPosY", "z_mm": "globalPosZ",
            "energy_kev": "energy",
        },
        "time_unit": "s", "position_unit": "cm", "energy_unit": "MeV",
    }


def write_root(path, **replacements):
    """寫出簡單 TTree，分支名稱只作為明確映射的測試資料。"""
    arrays = {
        "time": np.array([1e-9, 1.5e-9]),
        "crystalID": np.array([3, 9], dtype=np.int32),
        "globalPosX": np.array([40.0, -40.0]),
        "globalPosY": np.array([1.0, -1.0]),
        "globalPosZ": np.array([2.0, 3.0]),
        "energy": np.array([0.511, 0.499]),
    }
    arrays.update(replacements)
    with uproot.recreate(path) as root_file:
        root_file.mktree("DetectorHits", {
            name: "string" if values.dtype.kind in "OUS" else values.dtype
            for name, values in arrays.items()
        })
        root_file["DetectorHits"].extend(arrays)
    return path


def test_inspect_and_convert_units(tmp_path, mapping):
    path = write_root(tmp_path / "synthetic.root")
    info = inspect_root(path)
    assert info["trees"][0]["name"] == "DetectorHits"
    assert info["trees"][0]["num_entries"] == 2
    assert "time" in info["trees"][0]["branches"]
    frame = load_gate_singles(path, "DetectorHits", mapping)
    assert frame.timestamp_ps.tolist() == [1000, 1500]
    assert frame.detector_id.tolist() == [3, 9]
    assert frame.single_id.tolist() == [0, 1]
    assert frame.x_mm.tolist() == [400.0, -400.0]
    assert frame.energy_kev.tolist() == [511.0, 499.0]
    assert frame.timestamp_ps.dtype == np.dtype("int64")
    assert frame.arrival_time_ps.equals(frame.timestamp_ps.rename("arrival_time_ps"))
    assert frame.lane_id.tolist() == [0, 0]
    assert "truth_event_id" not in frame
    assert frame.attrs["provenance"]["placeholder_columns"]["lane_id"] == 0


def test_large_integer_times_do_not_pass_through_float(tmp_path, mapping):
    times = np.array([2**60 + 1, 2**60 + 2], dtype=np.int64)
    path = write_root(tmp_path / "integer.root", time=times)
    mapping["time_unit"] = "ps"
    frame = load_gate_singles(path, "DetectorHits", mapping)
    assert frame.timestamp_ps.tolist() == times.tolist()
    mapping["time_origin"] = str(2**60)
    assert load_gate_singles(path, "DetectorHits", mapping).timestamp_ps.tolist() == [1, 2]


def test_overflow_requires_explicit_origin(tmp_path, mapping):
    path = write_root(tmp_path / "absolute.root", time=np.array([10**9, 10**9 + 1]))
    with pytest.raises(ValueError, match="time_origin"):
        load_gate_singles(path, "DetectorHits", mapping)
    mapping["time_origin"] = "1000000000"
    assert load_gate_singles(path, "DetectorHits", mapping).timestamp_ps.tolist() == [0, 10**12]


def test_empty_and_bounded_reads(tmp_path, mapping):
    path = write_root(tmp_path / "bounded.root")
    empty = load_gate_singles(path, "DetectorHits", mapping, entry_stop=0)
    assert empty.empty
    assert empty.timestamp_ps.dtype == np.dtype("int64")
    assert len(load_gate_singles(path, "DetectorHits", mapping, entry_stop=1)) == 1
    assert empty.attrs["provenance"]["entries_in_tree"] == 2


@pytest.mark.parametrize("bad_stop", [-1, 1.5, True])
def test_invalid_entry_stop(tmp_path, mapping, bad_stop):
    with pytest.raises(ValueError, match="entry_stop"):
        load_gate_singles(tmp_path / "unused.root", "DetectorHits", mapping, bad_stop)


@pytest.mark.parametrize("key,value", [
    ("time_unit", "us"), ("position_unit", "inch"), ("energy_unit", ""),
    ("time_origin", "NaN"),
])
def test_requires_explicit_valid_units(tmp_path, mapping, key, value):
    mapping[key] = value
    with pytest.raises(ValueError, match=key):
        load_gate_singles(tmp_path / "unused.root", "DetectorHits", mapping)


def test_missing_tree_and_singles_branches(tmp_path, mapping):
    path = write_root(tmp_path / "missing.root")
    with pytest.raises(ValueError, match="找不到資料樹"):
        load_gate_singles(path, "Singles", mapping)
    mapping["fields"]["timestamp_ps"] = "time1"
    with pytest.raises(ValueError, match="Coincidences"):
        load_gate_singles(path, "DetectorHits", mapping)


def test_missing_required_mapping(tmp_path, mapping):
    del mapping["fields"]["detector_id"]
    with pytest.raises(ValueError, match="detector_id"):
        load_gate_singles(tmp_path / "unused.root", "DetectorHits", mapping)


@pytest.mark.parametrize("branch,values,match", [
    ("time", [float("nan"), 0], "有限"),
    ("energy", [float("inf"), 0.511], "非有限"),
    ("globalPosY", [0, float("nan")], "非有限"),
    ("crystalID", [1.5, 3.0], "不是整數"),
])
def test_reject_malformed_values(tmp_path, mapping, branch, values, match):
    path = write_root(tmp_path / "invalid.root", **{branch: np.array(values)})
    with pytest.raises(ValueError, match=match):
        load_gate_singles(path, "DetectorHits", mapping)


def test_optional_truth_is_explicit_and_preserved(tmp_path, mapping):
    path = write_root(
        tmp_path / "truth.root", eventID=np.array([4, 4]), runID=np.array([0, 1]),
        sourceX=np.array([1.0, 1.0]), sourceY=np.array([2.0, 2.0]),
        sourceZ=np.array([3.0, 3.0]),
    )
    mapping["fields"].update({
        "truth_event_id": "eventID", "truth_run_id": "runID",
        "truth_source_x_mm": "sourceX", "truth_source_y_mm": "sourceY",
        "truth_source_z_mm": "sourceZ",
    })
    frame = load_gate_singles(path, "DetectorHits", mapping)
    assert frame.truth_event_id.tolist() == [4, 4]
    assert frame.truth_run_id.tolist() == [0, 1]
    assert frame.truth_source_z_mm.tolist() == [30.0, 30.0]


def test_partial_truth_position_is_rejected(tmp_path, mapping):
    mapping["fields"]["truth_source_x_mm"] = "sourceX"
    with pytest.raises(ValueError, match="同時映射"):
        load_gate_singles(tmp_path / "unused.root", "DetectorHits", mapping)


def test_ns_rounding_rule(tmp_path, mapping):
    path = write_root(tmp_path / "round.root", time=np.array([0.0005, 0.0015]))
    mapping["time_unit"] = "ns"
    assert load_gate_singles(path, "DetectorHits", mapping).timestamp_ps.tolist() == [0, 2]


def test_explicit_categorical_detector_labels(tmp_path, mapping):
    path = write_root(
        tmp_path / "labels.root", crystalID=np.array(["ring_1/crystal_2", "ring_0/crystal_2"])
    )
    with pytest.raises(ValueError, match="detector_id"):
        load_gate_singles(path, "DetectorHits", mapping)
    mapping["detector_id_encoding"] = "categorical"
    frame = load_gate_singles(path, "DetectorHits", mapping)
    assert frame.detector_id.tolist() == [1, 0]
    assert frame.attrs["provenance"]["detector_id_label_map"] == {
        "ring_0/crystal_2": 0, "ring_1/crystal_2": 1,
    }
    # 有界載入只針對選取內容編碼，對照表明確記錄新的識別碼範圍。
    bounded = load_gate_singles(path, "DetectorHits", mapping, entry_stop=1)
    assert bounded.detector_id.tolist() == [0]
    assert bounded.attrs["provenance"]["detector_id_label_map"] == {"ring_1/crystal_2": 0}
    assert load_gate_singles(path, "DetectorHits", mapping, entry_stop=0).empty


def test_categorical_detector_rejects_empty_label(tmp_path, mapping):
    path = write_root(tmp_path / "blank.root", crystalID=np.array(["", "detector_1"]))
    mapping["detector_id_encoding"] = "categorical"
    with pytest.raises(ValueError, match="空字串"):
        load_gate_singles(path, "DetectorHits", mapping)


def test_unknown_detector_encoding(tmp_path, mapping):
    mapping["detector_id_encoding"] = "guess"
    with pytest.raises(ValueError, match="detector_id_encoding"):
        load_gate_singles(tmp_path / "unused.root", "DetectorHits", mapping)
