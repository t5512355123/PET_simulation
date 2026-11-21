"""EXP-S17/S18 end-to-end time budget of online list-mode psv on the DE10-Pro (R2 projector + voxel units), D690.
Schedule of the GPU run that passes at update 40 (M = 8): full gradients at updates 0, 16, 32 (8 subset projections
each, followed by 8 ACC readouts), 37 single-subset updates; preconditioner at updates 4 and 8.
Usage: python budget_r2.py [T_proj_ms per subset (fwd + back)] [DDR GB/s total] [f MHz]"""
import sys
T_PROJ = float(sys.argv[1]) if len(sys.argv) > 1 else 5.2
BW = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
F = float(sys.argv[3]) if len(sys.argv) > 3 else 150.0
NV = 1_475_659                      # FOV voxels
UPD, M, NFULL = 40, 8, 3
n_proj = (UPD - NFULL) + NFULL * M  # 61 subset projections (7.625 projection epochs)
lane_ops = 4 * NV / 40              # 2 copies x (read ACC + write IMG), 40 lanes, 1 op / lane / cycle
B_UPD = 2 + 2 + 4 + 4 + 4 + 4       # g_tab fp16, P fp16, g_sum, RDP grad, x old (read) + x new (write)
B_RD = 2 + 4 + 4                    # readout pass of a full gradient: g_tab fp16 write, g_sum read + write
t_upd = max(NV * B_UPD / (BW * 1e9), lane_ops / (F * 1e6))
t_rd = max(NV * B_RD / (BW * 1e9), lane_ops / 2 / (F * 1e6))
tot = n_proj * T_PROJ * 1e-3 + UPD * t_upd + NFULL * M * t_rd
print(f'subset projections {n_proj} x {T_PROJ} ms = {n_proj * T_PROJ:.0f} ms')
print(f'voxel update pass {t_upd * 1e3:.2f} ms x {UPD} = {UPD * t_upd * 1e3:.0f} ms ; readout pass {t_rd * 1e3:.2f} ms x {NFULL * M} '
      f'= {NFULL * M * t_rd * 1e3:.0f} ms ; (RDP gradient and preconditioner overlapped with the projection)')
print(f'total {tot * 1e3:.0f} ms ; GPU 2390 ms -> {2.39 / tot:.2f}x (target 5x: <= 478 ms); max T_proj for 5x: '
      f'{(0.478 - UPD * t_upd - NFULL * M * t_rd) / n_proj * 1e3:.2f} ms')
