// Gaussian unit body (EXP-S19, preconditioner): xs = G(x) over the full 201 x 201 x nz image, zero outside,
// separable x (9 taps, gx0 centre .. gx4), y (9 taps, gy0..gy4), z (7 taps, gz0..gz3); intermediates rounded to bf16
// (GPU-checked: psv still passes at update 40). 2 voxels (one pair) per iteration, raster stream with delay lines.
// Input: xin raster (D512, PS / RS layout, columns 0..199) + mb boundary words ((x, kappa) pairs: q 0..200 row 200,
// 201..400 column 200). Output: mo raster (D512, columns 0..200 and row 200 included; 201..207 = 0), fp32.
// Stream position (z, y, p): z = 0 .. nz + 2, y = 0 .. 204, p = 0 .. 102 (pair x = 2p - 4, 2p - 3 of the x-filter output
// is produced at p; pairs p = 0, 1 fill the window). x-filtered row y enters the y delay lines; the y-filter output of row
// y - 4 enters the z delay lines; the z-filter output of plane z - 3 is written.
// MEMATTRY / MEMATTRZ = memory attributes (empty in software).
#ifndef LDP
#define LDP(m, i) (m)[i]
#endif
{
  const int RW = 101, PL = 201 * 101, NYS = 205, NPS = 103;
  MEMATTRY static unsigned LY[8][RW];               // 8 previous x-filtered rows (pairs, 2 x bf16)
  MEMATTRZ static unsigned LZ[6][PL];               // 6 previous y-filtered planes (pairs, 2 x bf16)
  float GX[5] = {gx0, gx1, gx2, gx3, gx4}, GY[5] = {gy0, gy1, gy2, gy3, gy4}, GZ[4] = {gz0, gz1, gz2, gz3};
  int z = 0, y = 0, p = 0;
  long nin = (long)(nz + 3) * NYS * NPS;
  D512 wxi, wbi, wout;
#pragma unroll
  for (int e = 0; e < 16; e++) { wxi.v[e] = 0.0f; wbi.v[e] = 0.0f; wout.v[e] = 0.0f; }
  float SW[10];
#pragma unroll
  for (int c = 0; c < 10; c++) SW[c] = 0.0f;
#pragma ivdep
  for (long it = 0; it < nin; it++) {
    // ---- input pair (x = 2p, 2p + 1) of row y, plane z (zero outside 0..200 / planes >= nz)
    bool live = z < nz && y <= 200 && p <= 100;
    float x0 = 0.0f, x1 = 0.0f;
    long e = (long)z * PS + (long)y * RS + 2 * p;
    bool inner = live && y < 200 && p < 100;
    if (inner) {
      if ((e & 15) == 0) wxi = xin[e >> 4];
      x0 = wxi.v[e & 15]; x1 = wxi.v[(e + 1) & 15];
    }
    if (live && !inner) {
      int q0 = y == 200 ? 2 * p : 201 + y;
      int eb = 2 * q0;
      bool v1 = y == 200 && 2 * p + 1 <= 200;
      bool ld = (eb & 15) == 0 || p == 100 || (y == 200 && p == 0);
      if (ld) wbi = LDP(mb, z * RB_WORDS + (eb >> 4));
      x0 = wbi.v[eb & 15];
      x1 = v1 ? wbi.v[(eb + 2) & 15] : 0.0f;
    }
    x0 = bf2f(f2bf(x0)); x1 = bf2f(f2bf(x1));
    // ---- x-filter: window columns 2p - 8 .. 2p + 1 ; output pair x = 2p - 4, 2p - 3 (taps -4..+4)
#pragma unroll
    for (int c = 0; c < 8; c++) SW[c] = p == 0 ? 0.0f : SW[c + 2];
    SW[8] = x0; SW[9] = x1;
    float xf[2];
#pragma unroll
    for (int j = 0; j < 2; j++) {
      float a = GX[0] * SW[4 + j];
#pragma unroll
      for (int t = 1; t <= 4; t++) a += GX[t] * (SW[4 + j - t] + SW[4 + j + t]);
      xf[j] = a;
    }
    int xo = 2 * p - 4;                               // x of xf[0]
    bool xv0 = xo >= 0 && xo <= 200, xv1 = xo + 1 >= 0 && xo + 1 <= 200;
    unsigned xpk = (xv0 ? f2bf(xf[0]) : 0u) | ((xv1 ? f2bf(xf[1]) : 0u) << 16);
    // pair index of the x-filter output within the row: q = p - 2 (x = 2q, 2q + 1), valid 0..100
    int q = p - 2;
    bool qv = q >= 0 && q <= 100;
    int qa = qv ? q : 0;
    // ---- y delay lines: rows y - 8 .. y - 1 of the x-filtered stream at pair q
    unsigned ry[9];
#pragma unroll
    for (int r = 0; r < 8; r++) ry[r] = LY[r][qa];
    ry[8] = xpk;
    if (qv) {
#pragma unroll
      for (int r = 0; r < 7; r++) LY[r][qa] = ry[r + 1];
      LY[7][qa] = xpk;
    }
    // y-filter output for row yo = y - 4, pair q (rows outside 0..200 are zero: rows y - 8 + r < 0 or > 200 masked)
    float yf[2];
#pragma unroll
    for (int j = 0; j < 2; j++) {
      float a = 0.0f;
#pragma unroll
      for (int r = 0; r < 9; r++) {
        int row = y - 8 + r;
        int t = r - 4; t = t < 0 ? -t : t;
        float g = t == 0 ? GY[0] : (t == 1 ? GY[1] : (t == 2 ? GY[2] : (t == 3 ? GY[3] : GY[4])));
        float v = bf2f(j ? (ry[r] >> 16) : (ry[r] & 0xffffu));
        a += (row >= 0 && row <= 200 && z < nz) ? g * v : 0.0f;
      }
      yf[j] = a;
    }
    int yo = y - 4;
    bool yv = qv && yo >= 0 && yo <= 200;
    unsigned ypk = yv ? (f2bf(yf[0]) | (f2bf(yf[1]) << 16)) : 0u;
    // ---- z delay lines: planes z - 6 .. z - 1 at (yo, q)
    int ia = yv ? yo * RW + q : 0;
    unsigned rz[7];
#pragma unroll
    for (int r = 0; r < 6; r++) rz[r] = LZ[r][ia];
    rz[6] = ypk;
    if (yv) {
#pragma unroll
      for (int r = 0; r < 5; r++) LZ[r][ia] = rz[r + 1];
      LZ[5][ia] = ypk;
    }
    // z-filter output for plane zo = z - 3 at (yo, q)
    int zo = z - 3;
    float zf[2];
#pragma unroll
    for (int j = 0; j < 2; j++) {
      float a = 0.0f;
#pragma unroll
      for (int r = 0; r < 7; r++) {
        int pz = z - 6 + r;
        int t = r - 3; t = t < 0 ? -t : t;
        float g = t == 0 ? GZ[0] : (t == 1 ? GZ[1] : (t == 2 ? GZ[2] : GZ[3]));
        float v = bf2f(j ? (rz[r] >> 16) : (rz[r] & 0xffffu));
        a += (pz >= 0 && pz < nz) ? g * v : 0.0f;
      }
      zf[j] = a;
    }
    bool ov = yv && zo >= 0 && zo < nz;
    if (ov) {
      long eo = (long)zo * PS + (long)yo * RS + 2 * q;
      wout.v[eo & 15] = zf[0]; wout.v[(eo + 1) & 15] = (2 * q + 1 <= 200) ? zf[1] : 0.0f;
      if (q == 100) {
#pragma unroll
        for (int c = 10; c < 16; c++) wout.v[c] = 0.0f;
      }
      if ((eo & 15) == 14 || q == 100) mo[eo >> 4] = wout;
    }
    bool pl = p == NPS - 1, yl = pl && y == NYS - 1;
    p = pl ? 0 : p + 1; y = pl ? (yl ? 0 : y + 1) : y; z = yl ? z + 1 : z;
  }
}
