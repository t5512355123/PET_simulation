"""Local stand-in for PETRIC2 petric.py: same get_data(), construct_RDP() and metric formulas.
(No tensorboard / Unix 'resource'; data loading happens only when get_data() is called.)"""
from dataclasses import dataclass
from pathlib import Path, PurePath

import numpy as np
import sirf.STIR as STIR

STIR.set_max_omp_threads(8)  # same as petric.py


def construct_RDP(penalty_strength, initial_image, kappa, max_scaling=1e-3):
    prior = getattr(STIR, 'CudaRelativeDifferencePrior', STIR.RelativeDifferencePrior)()
    epsilon = initial_image.max() * max_scaling
    prior.set_epsilon(epsilon)
    prior.set_penalisation_factor(penalty_strength)
    prior.set_kappa(kappa)
    prior.set_up(initial_image)
    return prior


@dataclass
class Dataset:
    acquired_data: object
    additive_term: object
    mult_factors: object
    OSEM_image: object
    prior: object
    kappa: object
    reference_image: object
    whole_object_mask: object
    background_mask: object
    voi_masks: dict
    FOV_mask: object
    path: PurePath


def get_data(srcdir="."):
    srcdir = Path(srcdir)
    STIR.AcquisitionData.set_storage_scheme('memory')
    acquired_data = STIR.AcquisitionData(str(srcdir / 'prompts.hs'))
    additive_term = STIR.AcquisitionData(str(srcdir / 'additive_term.hs'))
    mult_factors = STIR.AcquisitionData(str(srcdir / 'mult_factors.hs'))
    OSEM_image = STIR.ImageData(str(srcdir / 'OSEM_image.hv'))
    FOV_mask = STIR.TruncateToCylinderProcessor().process(OSEM_image.allocate(1))
    kappa = STIR.ImageData(str(srcdir / 'kappa.hv'))
    if (pf := (srcdir / 'penalisation_factor.txt')).is_file():
        penalty_strength = float(np.loadtxt(pf))
    else:
        penalty_strength = 1 / 700
    prior = construct_RDP(penalty_strength, OSEM_image, kappa)

    def get_image(fname):
        if (source := srcdir / 'PETRIC' / fname).is_file():
            return STIR.ImageData(str(source))
        return None

    reference_image = get_image('reference_image.hv')
    whole_object_mask = get_image('VOI_whole_object.hv')
    background_mask = get_image('VOI_background.hv')
    voi_masks = {
        voi.stem[4:]: STIR.ImageData(str(voi))
        for voi in (srcdir / 'PETRIC').glob("VOI_*.hv") if voi.stem[4:] not in ('background', 'whole_object')}
    return Dataset(acquired_data, additive_term, mult_factors, OSEM_image, prior, kappa, reference_image,
                   whole_object_mask, background_mask, voi_masks, FOV_mask, srcdir.resolve())


class QualityMetrics:
    """Same formulas and thresholds as PETRIC2 petric.QualityMetrics."""
    THRESHOLD = {"AEM_VOI": 0.005, "RMSE_whole_object": 0.01, "RMSE_background": 0.01}

    def __init__(self, reference_image, whole_object_mask, background_mask, voi_mask_dict, threshold_window=10):
        self.whole_object_indices = np.where(whole_object_mask.as_array())
        self.background_indices = np.where(background_mask.as_array())
        self.ref_im_arr = reference_image.as_array()
        self.norm = self.ref_im_arr[self.background_indices].mean()
        self.voi_indices = {k: np.where(v.as_array()) for k, v in voi_mask_dict.items()}
        self.threshold_window = threshold_window
        self.threshold_iters = 0

    def evaluate(self, test_im):
        a = test_im.as_array()
        r = self.ref_im_arr
        w, b = self.whole_object_indices, self.background_indices
        out = {
            "RMSE_whole_object": float(np.sqrt(np.mean((r[w] - a[w]) ** 2)) / self.norm),
            "RMSE_background": float(np.sqrt(np.mean((r[b] - a[b]) ** 2)) / self.norm)}
        for name, idx in sorted(self.voi_indices.items()):
            out[f"AEM_VOI_{name}"] = float(abs(a[idx].mean() - r[idx].mean()) / self.norm)
        return out

    def passed(self, metrics):
        import re
        return all(v <= self.THRESHOLD[re.sub("^(AEM_VOI)_.*", r"\1", k)] for k, v in metrics.items())
