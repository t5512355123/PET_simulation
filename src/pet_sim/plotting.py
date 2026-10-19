"""產生可重現的離線 PNG，方便比較真配對與所有配對。"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def save_ror_plot(ror, path, source_mm=None, extent_mm=100.0):
    fig, axes = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=True)
    valid = ror.loc[ror.physical_tof_valid.astype(bool)]
    for ax, (a, b) in zip(axes[:2], [("x", "y"), ("x", "z")]):
        ax.hist2d(valid[f"ror_{a}_mm"], valid[f"ror_{b}_mm"], bins=80,
                  range=[[-extent_mm, extent_mm]] * 2, cmap="inferno")
        if source_mm is not None:
            idx = {"x": 0, "y": 1, "z": 2}
            ax.plot(source_mm[idx[a]], source_mm[idx[b]], "+", color="cyan", ms=12)
        ax.set(xlabel=f"{a} (mm)", ylabel=f"{b} (mm)", title=f"All valid pairs: {a.upper()}{b.upper()}")
        ax.set_aspect("equal")
    if source_mm is not None and "same_truth_event" in valid:
        truth = valid.loc[valid.same_truth_event.astype(bool)]
        points = truth[["ror_x_mm", "ror_y_mm", "ror_z_mm"]].to_numpy(float)
        errors = np.linalg.norm(points-np.asarray(source_mm), axis=1)
        axes[2].hist(errors, bins=60, color="steelblue")
        axes[2].set(xlabel="3D error (mm)", ylabel="Pairs", title="Same-event localization errors")
    else:
        axes[2].hist(ror.dt_ps, bins=60, color="steelblue")
        axes[2].set(xlabel="t2 - t1 (ps)", ylabel="Pairs", title="Coincidence time differences")
    fig.savefig(path, dpi=160)
    plt.close(fig)
