"""Is the PETRIC reference image a stationary point of OUR (STIR 6.5) objective? Per-plane KKT residual x*grad."""
import sys, numpy as np, stir, stir.extra as sx
D = sys.argv[1]
stir.set_num_threads(8)
rd = lambda f: stir.FloatVoxelsOnCartesianGrid.read_from_file(D + '/' + f)
y = stir.ProjDataInMemory(stir.ProjData.read_from_file(D + '/prompts.hs'))
add = stir.ProjDataInMemory(stir.ProjData.read_from_file(D + '/additive_term.hs'))
mult = stir.ProjDataInMemory(stir.ProjData.read_from_file(D + '/mult_factors.hs'))
osem = rd('OSEM_image.hv'); kappa = rd('kappa.hv'); ref = rd('PETRIC/reference_image.hv')
beta = float(np.loadtxt(D + '/penalisation_factor.txt'))
m = sx.to_numpy(mult.to_array()); inv = stir.ProjDataInMemory(mult); inv.fill(np.where(m > 0, 1 / np.maximum(m, 1e-20), 0).astype(np.float32).flat)
obj = stir.PoissonLogLikelihoodWithLinearModelForMeanAndProjData3DFloat()
obj.set_proj_data_sptr(y); obj.set_projector_pair_sptr(stir.ProjectorByBinPairUsingParallelproj())
obj.set_normalisation_sptr(stir.BinNormalisationFromProjData(inv)); obj.set_additive_proj_data_sptr(add)
obj.set_num_subsets(1); obj.set_up(ref)
gL = ref.get_empty_copy(); obj.compute_sub_gradient_without_penalty(gL, ref, 0); gL = sx.to_numpy(gL)
x = sx.to_numpy(ref)
res = {}
for name, cls in [('cuda', stir.CudaRelativeDifferencePrior3DFloat), ('cpu', stir.RelativeDifferencePrior3DFloat)]:
    p = cls(); p.set_epsilon(float(sx.to_numpy(osem).max() * 1e-3)); p.set_penalisation_factor(beta); p.set_kappa_sptr(kappa); p.set_up(ref)
    g = ref.get_empty_copy(); p.compute_gradient(g, ref); res[name] = sx.to_numpy(g)
print('cuda vs cpu prior grad rel diff', np.abs(res['cuda'] - res['cpu']).max() / np.abs(res['cpu']).max())
sens = obj.get_subset_sensitivity(0); sens = sx.to_numpy(sens)
for name in ['cuda', 'cpu']:
    g = gL - res[name]
    kkt = np.abs(x * g / np.maximum(sens, 1e-6))   # = |preconditioned step| with P = x/sens
    print(name, 'KKT residual per plane (mean |x*g/sens| / mean x):')
    for k in [0, 10, 11, 12, 50, 90, 91, 92, 93, 94]:
        print('  z', k, '%.2e' % (kkt[k].mean() / max(x[k].mean(), 1e-12)),
              ' likelihood part %.2e prior part %.2e' % (np.abs(x[k] * gL[k] / np.maximum(sens[k], 1e-6)).mean() / max(x[k].mean(), 1e-12),
                                                         np.abs(x[k] * res[name][k] / np.maximum(sens[k], 1e-6)).mean() / max(x[k].mean(), 1e-12)))
print('sens per plane mean', [round(float(sens[k].mean()), 3) for k in [0, 1, 50, 93, 94]])
