"""Split one STIR subset-gradient (what psv calls 8x per epoch) into its steps, using the same STIR objects.
usage: python decompose_subgrad.py <dataset_dir> <num_subsets> <out_json>"""
import json, sys, time
import numpy as np
import stir, stir.extra as sx

D, M, OUT = sys.argv[1], int(sys.argv[2]), sys.argv[3]
stir.set_num_threads(8)
T = {}
def tic(): return time.perf_counter()
y = stir.ProjDataInMemory(stir.ProjData.read_from_file(D + '/prompts.hs'))
add = stir.ProjDataInMemory(stir.ProjData.read_from_file(D + '/additive_term.hs'))
mult = stir.ProjDataInMemory(stir.ProjData.read_from_file(D + '/mult_factors.hs'))
x = stir.FloatVoxelsOnCartesianGrid.read_from_file(D + '/OSEM_image.hv')
info = y.get_proj_data_info()
obj = stir.PoissonLogLikelihoodWithLinearModelForMeanAndProjData3DFloat()   # same set-up as psv, gives set-up projectors
obj.set_proj_data_sptr(y); obj.set_projector_pair_sptr(stir.ProjectorByBinPairUsingParallelproj())
obj.set_additive_proj_data_sptr(add); obj.set_num_subsets(M); obj.set_up(x)
pp = obj.get_projector_pair(); fp, bp = pp.get_forward_projector(), pp.get_back_projector()
yarr = sx.to_numpy(y.to_array()); marr = sx.to_numpy(mult.to_array()); aarr = sx.to_numpy(add.to_array())
est = stir.ProjDataInMemory(y)
res = {}
for rep in range(3):
    r = {}
    t = tic(); fp.set_input(x); r['fwd_set_input(GPU全部投影+拷回host)'] = tic() - t
    t = tic(); fp.forward_project(est, 0, M); r['fwd_copy_subset_viewgrams'] = tic() - t
    t = tic(); e = sx.to_numpy(est.to_array()); r['(numpy轉換)'] = tic() - t
    t = tic()
    yhat = marr * (e + aarr)                       # additive + normalisation undo (STIR does this per viewgram)
    ratio = np.where(yhat > 0, marr * yarr / np.maximum(yhat, 1e-30), 0).astype(np.float32)
    r['ratio_y_over_yhat(CPU,全部bin)'] = tic() - t
    t = tic(); est.fill(ratio.ravel()); r['(numpy轉換2)'] = tic() - t
    t = tic(); bp.start_accumulating_in_new_target(); bp.back_project(est, 0, M)
    g = x.get_empty_copy(); bp.get_output(g); r['back_project_subset'] = tic() - t
    res[f'rep{rep}'] = r
    print(rep, {k: round(v, 3) for k, v in r.items()}, flush=True)
t = tic(); fp.set_input(x); fp.forward_project(est, 0, 1); full_fwd = tic() - t
t = tic(); bp.start_accumulating_in_new_target(); bp.back_project(est, 0, 1); g = x.get_empty_copy(); bp.get_output(g); full_back = tic() - t
res['full_fwd_all_views'] = full_fwd; res['full_back_all_views'] = full_back
res['bins_total'] = int(yarr.size); res['bins_nonzero'] = int((yarr > 0).sum())
print(res, flush=True)
json.dump(res, open(OUT, 'w'), indent=1, ensure_ascii=False)
