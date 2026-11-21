// Central voxel unit body (EXP-S18), included inside the HLS component and the software model.
// Needs: masters mx (X), mxn (XN write), mp (P bf16), mt (T bf16), mtw (T write), mg (GS / sens), mgw (GS write), mgp (GP);
//        registers mode, nd (diagonals), rep, step, Mf, invM; stream macros VOX_RA / VOX_RB / VOX_WA / VOX_WB.
// Diagonal d (slots 40 d .. 40 d + 39, k = d % 40): lanes deliver A (copy 1, slot l) then B (copy 0, slot (l - k) % 40)
// during diagonal d (iterations g = 0, 1); the 40 voxels are computed during d + 1 (8 per iteration, g = 0..4) and the
// new image values go back to the lanes during d + 2 (A at g = 0, B at g = 1).
// mode 0: x' = max(0, x + step P ((ACC - T) M - gp + gs)), lane = P > 0 ? x' : 0, XN = x'
// mode 1: same with d = gs (full-gradient update); mode 4: lane = P > 0 ? x : 0 (load, no DDR write)
// mode 2: T = bf16(ACC - gp / M), GS = ACC - gs(= sens) - gp; mode 3: T = bf16(ACC - gp / M), GS = gs + ACC; lane = 0
// mode 5 (no lane sweep): P = bf16(T > 0 ? x / (gs(= sens) + 2 gp(= H) x) : 0) -> mtw  (T = FOV mask)
// EXP-S19: modes 0 / 1 also write x' as a raster (mxr: plane stride PS, row stride RS, columns 0..199, 200..207 = 0)
// through a double tile-row buffer CBX (2 x 40 rows x 13 words x 16 banks), drained one word per iteration.
{
  MEMATTRV static float CBX[2 * 40 * 13][16];

  float Ac[LANES], Bc[LANES], Ap[LANES], Bp[LANES], LVn[LANES], LVp[LANES], WB[LANES];
#pragma unroll
  for (int l = 0; l < LANES; l++) { Ac[l] = 0.0f; Bc[l] = 0.0f; Ap[l] = 0.0f; Bp[l] = 0.0f; LVn[l] = 0.0f; LVp[l] = 0.0f; WB[l] = 0.0f; }
  D512 wx, wg, wgp, bxn, bgs;
  D512U wp, wt, btw;
#pragma unroll
  for (int e = 0; e < 16; e++) {
    wx.v[e] = 0.0f; wg.v[e] = 0.0f; wgp.v[e] = 0.0f; bxn.v[e] = 0.0f; bgs.v[e] = 0.0f; wp.v[e] = 0u; wt.v[e] = 0u; btw.v[e] = 0u;
  }
  bool upd = mode == 0 || mode == 1, rdo = mode == 2 || mode == 3, full = mode == 1, r0 = mode == 2, ld = mode == 4;
  bool pre = mode == 5, lanes = mode != 5;
  bool needx = upd || ld || pre, needg = upd || rdo || pre, needgp = mode == 0 || rdo || pre, needp = upd || ld;
  int ntr = nd / 200;                               // tile rows (200 diagonals each)
  int niter = (nd + 2) * 5 + 600;
  for (int r = 0; r < rep; r++) {
    int g = 0, d = 0, kd = 0, kp = 0, kpp = 0;
    int sidx = 0;                                   // first slot of the computed group (diagonal d - 1)
    // EXP-S21: sidx % 40, (sidx / 40) % 40, (sidx / 1600) % 5, sidx / 8000 as counters (the divisions by constants,
    // unrolled 8x, were 39k ALUTs); raster drain tile row dtr = 5 dz + dm likewise
    int sii = 0, skk = 0, stx = 0, sctr = 0;
    int dtr = 0, drow = 0, dw = 0, dz = 0, dm = 0;  // raster drain: tile row, row, word
#pragma ivdep
    for (int it = 0; it < niter; it++) {
      bool rdA = lanes && g == 0 && d < nd, rdB = lanes && g == 1 && d < nd;
      bool cmp = d >= 1 && d <= nd;
      bool wrA = lanes && g == 0 && d >= 2 && d <= nd + 1, wrB = lanes && g == 1 && d >= 2 && d <= nd + 1;
      float xnv[8], lvj[8]; int xcol[8];
      int ctr = sctr;                                // tile row being computed
      if (rdA) VOX_RA;
      if (rdB) VOX_RB;
      if (wrA) VOX_WA;
      if (wrB) {
#pragma unroll
        for (int l = 0; l < 1; l++) { }
        { int am = kpp == 0 ? 0 : LANES - kpp;   // WB[l] = LVp[(l - kpp) mod 40]: rotate left by 40 - kpp
{ float r0_[LANES];
#pragma unroll
  for (int l = 0; l < LANES; l++) r0_[l] = LVp[l];
#pragma unroll
  for (int b = 0; b < 6; b++) {
    float r1_[LANES];
#pragma unroll
    for (int l = 0; l < LANES; l++) { int m = l + (1 << b); m = m >= LANES ? m - LANES : m; r1_[l] = ((am >> b) & 1) ? r0_[m] : r0_[l]; }
#pragma unroll
    for (int l = 0; l < LANES; l++) r0_[l] = r1_[l];
  }
#pragma unroll
  for (int l = 0; l < LANES; l++) WB[l] = r0_[l]; }
        }
        VOX_WB;
      }
      if (cmp) {
        int w16 = sidx >> 4, h = (sidx >> 3) & 1, w32 = sidx >> 5, q = (sidx >> 3) & 3;
        if (h == 0) { if (needx) wx = mx[w16]; if (needg) wg = mg[w16]; if (needgp) wgp = mgp[w16]; }
        if (q == 0) { if (needp) wp = mp[w32]; if (mode == 0 || pre) wt = mt[w32]; }
#pragma unroll
        for (int j = 0; j < 8; j++) {
          int i = 8 * g + j;
          float acc = Ap[j], bq = Bp[j];          // Ap / Bp shift by 8 per group: slot 8g + j is at index j
          (void)i;
#ifdef VOXDBG
          if (sidx + j == VOXDBG) printf("VOXDBG slot %d g %d j %d d %d: A %g B %g T %g\n", sidx + j, g, j, d, acc, bq, 0.0f);
#endif
          acc = acc + bq;
          float x = wx.v[8 * h + j], gs = wg.v[8 * h + j], gp = wgp.v[8 * h + j];
          unsigned pw = wp.v[4 * q + (j >> 1)], tw = wt.v[4 * q + (j >> 1)];
          float P = bf2f((j & 1) ? (pw >> 16) : (pw & 0xffffu));
          float T = bf2f((j & 1) ? (tw >> 16) : (tw & 0xffffu));
          float dd = full ? gs : (acc - T) * Mf - gp + gs;
          float xn = x + step * P * dd;
          xn = xn > 0.0f ? xn : 0.0f;
          float tv = pre ? (T > 0.0f ? x / (gs + 2.0f * gp * x) : 0.0f) : acc - gp * invM;
          float gn = r0 ? acc - gs - gp : gs + acc;
          float lv = rdo ? 0.0f : (P > 0.0f ? (ld ? x : xn) : 0.0f);
          lvj[j] = lv;
          bxn.v[8 * h + j] = xn;
          { int ii = sii + j; int xi = ii + skk; xi = xi >= 40 ? xi - 40 : xi;   // sidx % 8 == 0: no wrap of ii
            xnv[j] = xn; xcol[j] = ((((ctr & 1) * 40 + ii) * 13) << 4) + 40 * stx + xi; }
          bgs.v[8 * h + j] = gn;
          unsigned tb = f2bf(tv);
          int e = 4 * q + (j >> 1);
          btw.v[e] = (j & 1) ? ((btw.v[e] & 0xffffu) | (tb << 16)) : ((btw.v[e] & 0xffff0000u) | tb);
        }
#pragma unroll
        for (int l = 0; l < LANES - 8; l++) { LVn[l] = LVn[l + 8]; Ap[l] = Ap[l + 8]; Bp[l] = Bp[l + 8]; }
#pragma unroll
        for (int j = 0; j < 8; j++) LVn[LANES - 8 + j] = lvj[j];
        if (h == 1 && upd) mxn[w16] = bxn;
        if (h == 1 && rdo) mgw[w16] = bgs;
        if (q == 3 && (rdo || pre)) mtw[w32] = btw;
      }
      // ---- raster: write the 8 new values (bank = column % 16, static) and drain one word of the previous tile row
      bool cw = cmp && upd;
#pragma unroll
      for (int b = 0; b < 16; b++) {
        bool hit = false; int ad = 0; float v = 0.0f;
#pragma unroll
        for (int j = 0; j < 8; j++) {
          bool m_ = (xcol[j] & 15) == b;
          hit = hit || m_; ad = m_ ? (xcol[j] >> 4) : ad; v = m_ ? xnv[j] : v;
        }
        if (cw && hit) CBX[ad][b] = v;
      }
      int done_tr = d < 1 ? 0 : (cmp ? ctr : ntr);   // tile rows < done_tr are complete
      bool dok = upd && dtr < done_tr;
      D512 rw_;
#pragma unroll
      for (int b = 0; b < 16; b++) {
        float v = CBX[((dtr & 1) * 40 + drow) * 13 + dw][b];
        rw_.v[b] = (16 * dw + b >= 200) ? 0.0f : v;
      }
      if (dok) {
        int zz = dz, yy = 40 * dm + drow;
        mxr[zz * (PS / 16) + yy * (RS / 16) + dw] = rw_;
        bool wl = dw == 12, rl = wl && drow == 39, ml = rl && dm == 4;
        dw = wl ? 0 : dw + 1; drow = wl ? (rl ? 0 : drow + 1) : drow; dtr = rl ? dtr + 1 : dtr;
        dm = rl ? (ml ? 0 : dm + 1) : dm; dz = ml ? dz + 1 : dz;
      }
      if (cmp) {
        sidx += 8;
        bool w1 = sii == 32, w2 = w1 && skk == 39, w3 = w2 && stx == 4;
        sii = w1 ? 0 : sii + 8; skk = w1 ? (w2 ? 0 : skk + 1) : skk; stx = w2 ? (w3 ? 0 : stx + 1) : stx;
        sctr = w3 ? sctr + 1 : sctr;
      }
      if (g == 4) {
        if (d >= 1) {
#pragma unroll
          for (int l = 0; l < LANES; l++) LVp[l] = LVn[l];
          kpp = kp;
        }
        if (d < nd) {
#pragma unroll
          for (int l = 0; l < LANES; l++) Ap[l] = Ac[l];
          // Bp[l] = Bc[(l + kd) mod 40]: rotate left by kd
{ float r0_[LANES];
#pragma unroll
  for (int l = 0; l < LANES; l++) r0_[l] = Bc[l];
#pragma unroll
  for (int b = 0; b < 6; b++) {
    float r1_[LANES];
#pragma unroll
    for (int l = 0; l < LANES; l++) { int m = l + (1 << b); m = m >= LANES ? m - LANES : m; r1_[l] = ((kd >> b) & 1) ? r0_[m] : r0_[l]; }
#pragma unroll
    for (int l = 0; l < LANES; l++) r0_[l] = r1_[l];
  }
#pragma unroll
  for (int l = 0; l < LANES; l++) Bp[l] = r0_[l]; }
        }
        kp = kd;
        kd = kd == LANES - 1 ? 0 : kd + 1;
        d++;
      }
      g = g == 4 ? 0 : g + 1;
    }
  }
}
