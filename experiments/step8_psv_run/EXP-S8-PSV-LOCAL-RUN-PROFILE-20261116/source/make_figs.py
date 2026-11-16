"""Figures for the psv HTML report (pp env, matplotlib). usage: python make_figs.py <out_dir>"""
import json, sys, base64, io
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
O = Path(sys.argv[1])
s = json.load(open(O / 'summary.json'))
figs = {}


def save(name, fig):
    b = io.BytesIO(); fig.savefig(b, format='png', dpi=130, bbox_inches='tight'); plt.close(fig)
    (O / f'{name}.png').write_bytes(b.getvalue())
    figs[name] = base64.b64encode(b.getvalue()).decode()


# 1) metrics vs competition time
r = s['records']
t = np.array([x['t_comp'] for x in r])
fig, ax = plt.subplots(figsize=(7.5, 3.6))
ax.semilogy(t, [x['metrics']['RMSE_whole_object'] for x in r], color='#2563eb', lw=2, label='RMSE 全物體')
ax.semilogy(t, [x['RMSE_whole_excl_last2'] for x in r], color='#2563eb', lw=1.5, ls='--', label='RMSE 全物體（去掉最後 2 平面）')
ax.semilogy(t, [x['metrics']['RMSE_background'] for x in r], color='#16a34a', lw=2, label='RMSE 背景')
ax.semilogy(t, [max(v for k, v in x['metrics'].items() if k.startswith('AEM')) for x in r], color='#ea580c', lw=2, label='VOI 平均誤差（最大）')
ax.axhline(0.01, color='#2563eb', lw=0.8, ls=':'); ax.axhline(0.005, color='#ea580c', lw=0.8, ls=':')
ax.axvline(s['t_setup'], color='gray', lw=0.8); ax.text(s['t_setup'], 0.1, ' setup 結束', color='gray', fontsize=8)
if s.get('pass2_time_competition'):
    ax.axvline(s['pass2_time_competition'], color='k', lw=0.8, ls='--')
    ax.text(s['pass2_time_competition'], 0.05, ' 到達門檻\n（去掉最後2平面）', fontsize=8)
ax.set_yticks([0.002, 0.005, 0.01, 0.02, 0.05, 0.1]); ax.set_yticklabels(['0.2%', '0.5%', '1%', '2%', '5%', '10%']); ax.minorticks_off()
ax.set_xlabel('比賽計時（秒，讀檔後開始，不含評分）'); ax.set_ylabel('相對誤差'); ax.grid(alpha=0.3, which='both')
ax.legend(fontsize=8, loc='upper right'); ax.set_xlim(0, t.max() * 1.02)
save('fig_metrics', fig)

# 2) images: OSEM / init / pass / reference, slice through rods (z = 20 per PETRIC DATA_SLICES)
z = 20
imgs = [('OSEM（比賽提供）', np.load(O / 'x_osem.npy')), ('初始影像（OSEM+6mm濾波）', np.load(O / 'x_init.npy'))]
p2 = s.get('pass2_update')
cand = sorted(O.glob('x_upd*.npy'))
if p2 and (O / f'x_upd{p2:04d}.npy').is_file():
    imgs.append((f'psv 第 {p2} 次更新（約 {p2 / s["num_subsets"]:.1f} epoch）', np.load(O / f'x_upd{p2:04d}.npy')))
imgs.append(('參考影像（收斂的 MAP）', np.load(O / 'x_ref.npy')))
vmax = np.percentile(imgs[-1][1][z], 99.8)
fig, axs = plt.subplots(1, len(imgs), figsize=(3 * len(imgs), 3.2))
for ax, (ttl, im) in zip(axs, imgs):
    ax.imshow(im[z], cmap='Greys', vmin=0, vmax=vmax); ax.set_title(ttl, fontsize=9); ax.axis('off')
save('fig_images', fig)
json.dump(figs, open(O / 'figs_b64.json', 'w'))
print('ok', list(figs))
