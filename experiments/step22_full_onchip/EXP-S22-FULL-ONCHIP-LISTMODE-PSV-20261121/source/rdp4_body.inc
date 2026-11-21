// RDP unit body v4 (EXP-S19): gradient (mode 0) / diagonal Hessian (mode 1) of beta * RDP (gamma = 2) for the voxel slots
// (z, y < 200, x < 200); ONE voxel per iteration (meant for its own fast clock domain), fp32.
// Input raster: xin (D512; plane stride PS = 201 * RS floats, row stride RS = 208; columns 0..199 used, or the full
//   201 x 201 when braster != 0), kin (D512U, kappa bf16, full 201 x 201 raster), mb (boundary words per plane:
//   (x, kappa) pairs, q = 0..200 row y = 200 (x = q), q = 201..400 column x = 200 (y = q - 201); x used).
// Output: mo in SLOT order (D512): the raster results of one tile row (40 rows x 200 columns) go into a double buffer
//   CB and are drained in slot order (tiles tx = 0..4, diagonals k, positions i) while the next tile row is computed.
// Stream: voxel x (0..200) of row y (0..200) of plane z (0..nz; plane nz = zeros); at input (z, y, x) the output voxel
//   is (z - 1, y - 1, x - 1). MEMATTRX / MEMATTRK / MEMATTRC = memory attributes (empty in software).
#ifndef LDP
#define LDP(m, i) (m)[i]
#endif
{
  const int RW = 201, PL = 201 * 201, PLR = PL - 2 * RW;
  MEMATTRX static float LX1[RW], LX2[RW], LX3[PLR], LX4[RW], LX5[RW], LX6[PLR], LX7[RW], LX8[RW];
  MEMATTRK static unsigned short LK1[RW], LK2[RW], LK3[PLR], LK4[RW], LK5[RW], LK6[PLR], LK7[RW], LK8[RW];
  MEMATTRC static float CB[2 * 40 * 200];
  int z = 0, y = 0, x = 0, ia = 0, ib = 0;
  long nin = (long)(nz + 1) * PL;
  int ntr = nz * 5;                        // tile rows
  int dtr = 0, dn = 0;                     // drain: tile row, slot within it (0..7999)
  long nit = nin + 8100;
  D512 wxi, wout, wbi;
  D512U wki;
#pragma unroll
  for (int e = 0; e < 16; e++) { wxi.v[e] = 0.0f; wout.v[e] = 0.0f; wbi.v[e] = 0.0f; wki.v[e] = 0u; }
  float WX[3][3][3], WK[3][3][3];
#pragma unroll
  for (int a = 0; a < 3; a++)
#pragma unroll
    for (int b = 0; b < 3; b++)
#pragma unroll
      for (int c = 0; c < 3; c++) { WX[a][b][c] = 0.0f; WK[a][b][c] = 0.0f; }
  int ctr = 0;                             // tile rows completed by the writer
#pragma ivdep
  for (long it = 0; it < nit; it++) {
    bool strm = it < nin;
    bool live = strm && z < nz;
    float x0 = 0.0f, k0 = 0.0f;
    long e = (long)z * PS + (long)y * RS + x;
    bool inner = live && y < 200 && x < 200;
    bool xr = live && (braster != 0 || inner);
    if (live) {
      if ((e & 15) == 0) wxi = xin[e >> 4];
      if ((e & 31) == 0 || x == 0) wki = kin[e >> 5];
    }
    if (xr) x0 = wxi.v[e & 15];
    if (live) { unsigned kw = wki.v[(e & 31) >> 1]; k0 = bf2f((e & 1) ? (kw >> 16) : (kw & 0xffffu)); }
    if (live && !xr) {
      int q0 = y == 200 ? x : 201 + y;
      int eb = 2 * q0;
      bool ld = (eb & 15) == 0 || x == 200 || (y == 200 && x == 0);
      if (ld) wbi = LDP(mb, z * RB_WORDS + (eb >> 4));
      x0 = wbi.v[eb & 15];
    }
    unsigned short kh = (unsigned short)f2bf(k0);
    // ---- delay lines: T[plane][row], plane 2 = z, 1 = z - 1, 0 = z - 2; row 2 = y, 1 = y - 1, 0 = y - 2
    float TX[3][3];
    unsigned short TK[3][3];
    TX[2][2] = x0; TK[2][2] = kh;
    if (strm) {
      float a1 = LX1[ia], a2 = LX2[ia], a3 = LX3[ib], a4 = LX4[ia], a5 = LX5[ia], a6 = LX6[ib], a7 = LX7[ia], a8 = LX8[ia];
      unsigned short b1 = LK1[ia], b2 = LK2[ia], b3 = LK3[ib], b4 = LK4[ia], b5 = LK5[ia], b6 = LK6[ib], b7 = LK7[ia], b8 = LK8[ia];
      LX1[ia] = x0; LX2[ia] = a1; LX3[ib] = a2; LX4[ia] = a3; LX5[ia] = a4; LX6[ib] = a5; LX7[ia] = a6; LX8[ia] = a7;
      LK1[ia] = kh; LK2[ia] = b1; LK3[ib] = b2; LK4[ia] = b3; LK5[ia] = b4; LK6[ib] = b5; LK7[ia] = b6; LK8[ia] = b7;
      TX[2][1] = a1; TX[2][0] = a2; TX[1][2] = a3; TX[1][1] = a4; TX[1][0] = a5; TX[0][2] = a6; TX[0][1] = a7; TX[0][0] = a8;
      TK[2][1] = b1; TK[2][0] = b2; TK[1][2] = b3; TK[1][1] = b4; TK[1][0] = b5; TK[0][2] = b6; TK[0][1] = b7; TK[0][0] = b8;
#pragma unroll
      for (int a = 0; a < 3; a++)
#pragma unroll
        for (int b = 0; b < 3; b++) {
          WX[a][b][0] = WX[a][b][1]; WX[a][b][1] = WX[a][b][2]; WX[a][b][2] = TX[a][b];
          WK[a][b][0] = WK[a][b][1]; WK[a][b][1] = WK[a][b][2]; WK[a][b][2] = bf2f(TK[a][b]);
        }
    }
    // ---- output voxel (oz, oy, ox) = (z - 1, y - 1, x - 1) at window centre [1][1][1]
    int oz = z - 1, oy = y - 1, ox = x - 1;
    bool outv = strm && oz >= 0 && oy >= 0 && oy < 200 && ox >= 0 && ox < 200;
    float xc = WX[1][1][1], kc = WK[1][1][1], acc = 0.0f;
    float wkc[5] = {w1 * kc, w2 * kc, w3 * kc, w4 * kc, w5 * kc};
#pragma unroll
    for (int dz = 0; dz < 3; dz++)
#pragma unroll
      for (int dy = 0; dy < 3; dy++)
#pragma unroll
        for (int dx = 0; dx < 3; dx++) {
          if (dz == 1 && dy == 1 && dx == 1) continue;
          bool nv = !(dz == 0 && oz == 0) && !(dy == 0 && oy == 0) && !(dx == 0 && ox == 0);
          int nxy = (dy != 1) + (dx != 1);
          int ty = dz == 1 ? (nxy == 1 ? 0 : 1) : (nxy == 0 ? 2 : (nxy == 1 ? 3 : 4));
          float xk = WX[dz][dy][dx], kk = nv ? WK[dz][dy][dx] : 0.0f;
          float wk = wkc[ty] * kk;
          float d = xc - xk, ad = fabsf(d);
          float ga = ad + ad;
          float phi = xc + xk + ga + eps2;
          float r = 1.0f / phi;
          float th = xk + xk + eps2;
          float u = (mode == 0 ? d : th) * r;
          float v = mode == 0 ? 2.0f - (d + ga) * r : 2.0f * th * r * r;
          acc += wk * (u * v);
        }
    // ---- write the output into the tile-row buffer (raster within the tile row)
    int otr = oz * 5 + oy / 40;            // tile row of the output voxel
    int wh = otr & 1;
    if (outv) CB[(wh * 40 + oy % 40) * 200 + ox] = acc;
    if (outv && ox == 199 && oy % 40 == 39) ctr = otr + 1;
    // ---- drain one slot of tile row dtr (complete when ctr > dtr)
    bool dok = dtr < ntr && ctr > dtr;
    int sn = dn;                           // slot within the tile row: tx = sn / 1600, k, i
    int tx = sn / 1600, k = (sn / 40) % 40, i = sn % 40;
    int xi = i + k; xi = xi >= 40 ? xi - 40 : xi;
    float dv = CB[((dtr & 1) * 40 + i) * 200 + 40 * tx + xi];
    if (dok) {
      long gs = (long)dtr * 8000 + sn;
      wout.v[gs & 15] = dv;
      if ((gs & 15) == 15) mo[gs >> 4] = wout;
      bool last = dn == 7999;
      dn = last ? 0 : dn + 1;
      dtr = last ? dtr + 1 : dtr;
    }
    if (strm) {
      ia = ia == RW - 1 ? 0 : ia + 1;
      ib = ib == PLR - 1 ? 0 : ib + 1;
      bool xl = x == RW - 1, yl = xl && y == 200;
      x = xl ? 0 : x + 1; y = xl ? (yl ? 0 : y + 1) : y; z = yl ? z + 1 : z;
    }
  }
}
