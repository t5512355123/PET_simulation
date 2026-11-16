"""Replacement for sirf.contrib.partitioner.data_partition.

SIRF splits the sinogram into M view-staggered subsets (ProjDataInfoSubsetByView), one objective each.
STIR Python does not expose ProjDataInfoSubsetByView, so ONE STIR objective with set_num_subsets(M)
is used instead. STIR subsets are also view-staggered (subset s = views s, s+M, ...), so the
mathematics is the same; the projection cost per subset can differ (measured separately).
"""
import numpy as np
import stir
from prof import sec
from sirf.STIR import proj_to_numpy


class _SubsetObjective:
    def __init__(self, obj, s, tmpl_img):
        self.obj, self.s, self.tmpl = obj, s, tmpl_img

    def gradient(self, img):
        with sec('likelihood_gradient'):
            x = img.to_stir()
            g = x.get_empty_copy()
            self.obj.compute_sub_gradient_without_penalty(g, x, self.s)
            return img._from_stir(g)

    def get_subset_sensitivity(self, _):
        return self.tmpl._from_stir(self.obj.get_subset_sensitivity(self.s))


def data_partition(prompts, additive, mult, num_batches, initial_image=None, mode="staggered", **kw):
    assert mode == "staggered"
    with sec('setup_objective_and_subset_sensitivities'):
        obj = stir.PoissonLogLikelihoodWithLinearModelForMeanAndProjData3DFloat()
        obj.set_proj_data_sptr(prompts.pd)
        obj.set_projector_pair_sptr(stir.ProjectorByBinPairUsingParallelproj())
        # SIRF AcquisitionSensitivityModel(mult) stores 1/mult as STIR normalisation factors
        inv = stir.ProjDataInMemory(mult.pd)
        m = proj_to_numpy(mult.pd)
        inv.fill(np.where(m > 1e-20, 1.0 / np.maximum(m, 1e-20), 0).astype(np.float32).ravel())
        obj.set_normalisation_sptr(stir.BinNormalisationFromProjData(inv))
        obj.set_additive_proj_data_sptr(additive.pd)
        obj.set_num_subsets(int(num_batches))
        obj.set_up(initial_image.to_stir())
    data_partition.obj = obj
    data_partition.keep = [inv]
    return None, None, [_SubsetObjective(obj, s, initial_image) for s in range(int(num_batches))]
