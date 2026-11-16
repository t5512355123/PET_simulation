"""Toy example for the report: 2 voxels, 4 LORs, 2 subsets, psv update rule (same formulas as main.py)."""
import json
import numpy as np

A = np.array([[1.0, 0.0], [0.5, 0.5], [0.0, 1.0], [0.8, 0.2]])   # system matrix (4 LORs x 2 voxels)
m = np.array([0.9, 0.8, 1.0, 0.7])                                 # mult_factors (attenuation*norm)
a = np.array([0.2, 0.2, 0.2, 0.2])                                 # additive term (scatter+randoms, before m)
y = np.array([4.0, 2.0, 1.0, 3.0])                                 # prompts (counts)
subsets = [np.array([0, 2]), np.array([1, 3])]                     # view-staggered subsets
beta, eps, gamma = 0.5, 0.01, 2.0                                  # RDP strength, smoothing, gamma
M = len(subsets)


def lik_grad(x, idx):
    yhat = m[idx] * (A[idx] @ x + a[idx])
    return A[idx].T @ (m[idx] * y[idx] / yhat) - A[idx].T @ m[idx], yhat


def rdp_grad(x):  # rdp.py _gradient: sum over neighbours of w*d*(2phi-(d+gamma|d|))/phi^2, scaled by beta
    g = []
    for j, k in ((0, 1), (1, 0)):
        d = x[j] - x[k]; s = x[j] + x[k]; phi = s + gamma * abs(d) + eps
        g.append(beta * d * (2 * phi - (d + gamma * abs(d))) / phi ** 2)
    return np.array(g)


def rdp_diag_hess(x):  # rdp.py _diag_hessian: 2*(s-d+eps)^2/phi^3 = 2*(2*x_k+eps)^2/phi^3
    h = []
    for j, k in ((0, 1), (1, 0)):
        d = x[j] - x[k]; s = x[j] + x[k]; phi = s + gamma * abs(d) + eps
        h.append(beta * 2 * (s - d + eps) ** 2 / phi ** 3)
    return np.array(h)


x = np.array([2.0, 1.0])
sens = sum(A[i].T @ m[i] for i in subsets)
P = x / (sens + 2.0 * rdp_diag_hess(x) * x)
steps = []
# update 0 (epoch 0): full gradient pass, store every subset gradient
g_sub = [lik_grad(x, idx)[0] - rdp_grad(x) / M for idx in subsets]
yhat0 = [lik_grad(x, idx)[1] for idx in subsets]
g_sum = sum(g_sub)
alpha = 0.8
x1 = np.maximum(0, x + alpha * P * g_sum)
steps.append(dict(name='update 0 (full gradient)', x_before=x.tolist(), yhat=[v.tolist() for v in yhat0],
                  g_sub=[g.tolist() for g in g_sub], g_sum=g_sum.tolist(), P=P.tolist(), alpha=alpha, x_after=x1.tolist()))
# update 1: subset 1, SVRG correction
k = 1
gk_new = lik_grad(x1, subsets[k])[0] - rdp_grad(x1) / M
g_tilde = (gk_new - g_sub[k]) * M + g_sum
alpha1 = 0.8 / (1 + 0.01 * 1)
x2 = np.maximum(0, x1 + alpha1 * P * g_tilde)
steps.append(dict(name='update 1 (subset 1, SVRG)', x_before=x1.tolist(), gk_new=gk_new.tolist(), gk_old=g_sub[k].tolist(),
                  g_tilde=g_tilde.tolist(), alpha=alpha1, x_after=x2.tolist()))


# reference: MAP solution by many full-gradient steps
def full_grad(x):
    return sum(lik_grad(x, idx)[0] for idx in subsets) - rdp_grad(x)


xr = np.array([2.0, 1.0])
for _ in range(20000):
    xr = np.maximum(1e-9, xr + 0.01 * full_grad(xr))
out = dict(A=A.tolist(), m=m.tolist(), a=a.tolist(), y=y.tolist(), subsets=[s.tolist() for s in subsets],
           beta=beta, eps=eps, sens=sens.tolist(), steps=steps, x_map=xr.tolist())
print(json.dumps(out, indent=1))
json.dump(out, open('toy.json', 'w'), indent=1)


# full psv-style run on the toy (same schedule: full gradient at epochs 0,2,4..., random subset order)
S0 = float(__import__("os").environ.get("S0", "0.5"))
rng = np.random.default_rng(1)
x = np.array([2.0, 1.0]); traj = [x.tolist()]
P = x / (sens + 2.0 * rdp_diag_hess(x) * x)
upd = 0; order = []
for ep in range(12):
    for _ in range(M):
        if upd == 4 or (upd // M == 1 and upd % M == 0):
            P = x / (sens + 2.0 * rdp_diag_hess(x) * x)
        alpha = S0 / (1 + 0.01 * upd)
        if upd % M == 0 and (upd // M) % 2 == 0:
            g_sub = [lik_grad(x, idx)[0] - rdp_grad(x) / M for idx in subsets]; g_sum = sum(g_sub); g = g_sum
        else:
            if not order: order = list(rng.permutation(M))
            k = order.pop()
            g = (lik_grad(x, subsets[k])[0] - rdp_grad(x) / M - g_sub[k]) * M + g_sum
        x = np.maximum(0, x + alpha * P * g); upd += 1; traj.append(x.tolist())
out['traj'] = traj
json.dump(out, open('toy.json', 'w'), indent=1)
print([[round(a, 3) for a in t] for t in traj[:12]], traj[-1], xr)
