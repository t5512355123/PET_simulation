// psv voxel unit: streaming RDP gradient (3x3x3 line buffers) + SVRG combine + preconditioned step + max(0, .)
// One voxel per clock (II=1). Voxel records are read through Avalon-MM hosts (same interface as DDR).
//
//   gradR_j = sum_{k in 26 nb} w_jk kap_j kap_k d (2 phi - (d + g|d|)) / phi^2,  d = x_j - x_k, phi = x_j + x_k + g|d| + eps
//   mode 0 (subset / full-gradient step):  dir = M (B - gk) - sigma (s + beta gradR) + gsum ;  x' = max(0, x + alpha P dir)
//          out = (x', 0)
//   mode 1 (gradient-table entry):         gk' = B - (s + beta gradR) / M ;  out = (gk', gsum + gk')
// B = c A_k^T(m / yhat) from the projector lanes, gk = stored subset gradient, gsum = sum of the table,
// s = sensitivity (whole data), P = preconditioner, kap = RDP kappa.
#include "HLS/hls.h"
#include "HLS/stdio.h"
#include "HLS/math.h"
#include <stdlib.h>
#include <vector>

#ifndef NX
#define NX 163
#endif
#ifndef NY
#define NY 163
#endif
#define PLANE (NX * NY)
#define DLY (PLANE + NX + 1)          // input index ahead of the window centre

struct Rec {                          // 32 bytes per voxel
  float x, B, gk, gsum, s, P, kap, pad;
};
struct Out {
  float a, b;
};
struct float2 {
  float x, y;
};
static inline float2 mk2(float a, float b) { float2 r; r.x = a; r.y = b; return r; }
struct C5 {                           // centre-voxel fields carried on chip for DLY clocks
  float B, gk, gsum, s, P;
};

typedef ihc::mm_master<Rec, ihc::aspace<1>, ihc::awidth<32>, ihc::dwidth<256>, ihc::latency<0>, ihc::maxburst<1>,
                       ihc::align<32>, ihc::waitrequest<true> > RecPort;
typedef ihc::mm_master<Out, ihc::aspace<3>, ihc::awidth<32>, ihc::dwidth<64>, ihc::latency<0>, ihc::maxburst<1>,
                       ihc::align<8>, ihc::waitrequest<true> > OutPort;

hls_avalon_slave_component component void psv_update(
    hls_avalon_slave_register_argument RecPort &ahead,     // each record read once; centre fields wait DLY clocks on chip
    hls_avalon_slave_register_argument OutPort &out,
    hls_avalon_slave_register_argument int nz,
    hls_avalon_slave_register_argument int mode,
    hls_avalon_slave_register_argument float M,
    hls_avalon_slave_register_argument float sigma,
    hls_avalon_slave_register_argument float alpha,
    hls_avalon_slave_register_argument float beta,
    hls_avalon_slave_register_argument float eps,
    hls_avalon_slave_register_argument float gamma,
    hls_avalon_slave_register_argument float wf,    // weight of face neighbours (vx/vx = 1 for isotropic voxels)
    hls_avalon_slave_register_argument float we,    // edge neighbours (1/sqrt2)
    hls_avalon_slave_register_argument float wc,    // corner neighbours (1/sqrt3)
    hls_avalon_slave_register_argument int rep) {   // repeat the whole pass (timing only)
  // two plane delays and, per plane stream, two row delays; x and kappa packed together
  static float2 pd1[PLANE], pd2[PLANE];
  // one row-delay pair per plane stream, separate arrays so each has 1 read + 1 write per clock (stall-free)
  static float2 ra0[NX], rb0[NX], ra1[NX], rb1[NX], ra2[NX], rb2[NX];
  // centre-field delay: one array per field so every array has 1 read + 1 write per clock (stall-free)
  static float cbB[DLY], cbK[DLY], cbS[DLY], cbN[DLY], cbP[DLY];
  float2 w[3][3][3];
#pragma unroll
  for (int a = 0; a < 3; a++)
#pragma unroll
    for (int b = 0; b < 3; b++)
#pragma unroll
      for (int c = 0; c < 3; c++) w[a][b][c] = mk2(0.0f, 0.0f);

  const int n = nz * PLANE;
  for (int r_ = 0; r_ < rep; r_++) {
  int pi = 0, ri = 0, ci = 0;         // circular indices of the plane, row and centre delays
  int jx = 0, jy = 0, jz = 0;
  int j = -DLY;
// line-buffer slots are revisited only after NX (rows) or PLANE (planes) iterations
#pragma ii 1
#pragma ivdep array(pd1)
#pragma ivdep array(pd2)
#pragma ivdep array(ra0)
#pragma ivdep array(rb0)
#pragma ivdep array(ra1)
#pragma ivdep array(rb1)
#pragma ivdep array(ra2)
#pragma ivdep array(rb2)
#pragma ivdep array(cbB)
#pragma ivdep array(cbK)
#pragma ivdep array(cbS)
#pragma ivdep array(cbN)
#pragma ivdep array(cbP)
  for (int t = 0; t < n + DLY; t++) {
    float2 v = mk2(0.0f, 0.0f);
    C5 cin = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
    if (t < n) {
      Rec r = ahead[t];
      v = mk2(r.x, r.kap);
      cin.B = r.B; cin.gk = r.gk; cin.gsum = r.gsum; cin.s = r.s; cin.P = r.P;
    }
    C5 r;                             // record t - DLY = centre voxel j
    r.B = cbB[ci]; r.gk = cbK[ci]; r.gsum = cbS[ci]; r.s = cbN[ci]; r.P = cbP[ci];
    cbB[ci] = cin.B; cbK[ci] = cin.gk; cbS[ci] = cin.gsum; cbN[ci] = cin.s; cbP[ci] = cin.P;
    ci = (ci == DLY - 1) ? 0 : ci + 1;
    float2 p1 = pd1[pi], p2 = pd2[pi];
    pd1[pi] = v; pd2[pi] = p1;
    pi = (pi == PLANE - 1) ? 0 : pi + 1;
    float2 col[3][3];
    float2 s0[3] = {v, p1, p2};       // dz = +1, 0, -1
    {
      float2 a0 = ra0[ri], b0 = rb0[ri]; ra0[ri] = s0[0]; rb0[ri] = a0;
      float2 a1 = ra1[ri], b1 = rb1[ri]; ra1[ri] = s0[1]; rb1[ri] = a1;
      float2 a2 = ra2[ri], b2 = rb2[ri]; ra2[ri] = s0[2]; rb2[ri] = a2;
      col[0][0] = s0[0]; col[0][1] = a0; col[0][2] = b0;   // dy = +1, 0, -1
      col[1][0] = s0[1]; col[1][1] = a1; col[1][2] = b1;
      col[2][0] = s0[2]; col[2][1] = a2; col[2][2] = b2;
    }
    ri = (ri == NX - 1) ? 0 : ri + 1;
#pragma unroll
    for (int p = 0; p < 3; p++)
#pragma unroll
      for (int q = 0; q < 3; q++) {
        w[p][q][0] = w[p][q][1]; w[p][q][1] = w[p][q][2]; w[p][q][2] = col[p][q];   // [2] = dx +1, [1] = 0, [0] = -1
      }
    if (j >= 0) {
      float xj = w[1][1][1].x, kj = w[1][1][1].y;
      float g = 0.0f;
#pragma unroll
      for (int p = 0; p < 3; p++)
#pragma unroll
        for (int q = 0; q < 3; q++)
#pragma unroll
          for (int c = 0; c < 3; c++) {
            if (p == 1 && q == 1 && c == 1) continue;
            int dz = 1 - p, dy = 1 - q, dx = c - 1;
            bool ok = !((dz < 0 && jz == 0) || (dz > 0 && jz == nz - 1) || (dy < 0 && jy == 0) || (dy > 0 && jy == NY - 1) ||
                        (dx < 0 && jx == 0) || (dx > 0 && jx == NX - 1));
            int nn = (dz != 0) + (dy != 0) + (dx != 0);
            float wg = (nn == 1) ? wf : ((nn == 2) ? we : wc);
            float xk = w[p][q][c].x, kk = w[p][q][c].y;
            float d = xj - xk, ad = (d < 0.0f) ? -d : d;
            float phi = xj + xk + gamma * ad + eps;
            float term = wg * kj * kk * d * (2.0f * phi - (d + gamma * ad)) / (phi * phi);
            g += ok ? term : 0.0f;
          }
      float pr = r.s + beta * g;
      Out o;
      if (mode == 0) {
        float dir = M * (r.B - r.gk) - sigma * pr + r.gsum;
        float xn = xj + alpha * r.P * dir;
        o.a = xn > 0.0f ? xn : 0.0f; o.b = 0.0f;
      } else {
        float gkn = r.B - pr / M;
        o.a = gkn; o.b = r.gsum + gkn;
      }
      out[j] = o;
      jx++;
      if (jx == NX) { jx = 0; jy++; if (jy == NY) { jy = 0; jz++; } }
    }
    j++;
  }
  }
}

#ifndef NO_TESTBENCH
// reference (double) and emulation check on random data
static double ref_grad(const std::vector<Rec> &R, int nz, int z, int y, int x, double eps, double gam, double wf, double we, double wc) {
  int i = (z * NY + y) * NX + x;
  double xj = R[i].x, kj = R[i].kap, g = 0;
  for (int dz = -1; dz <= 1; dz++) for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
    if (!dz && !dy && !dx) continue;
    int Z = z + dz, Y = y + dy, X = x + dx;
    if (Z < 0 || Z >= nz || Y < 0 || Y >= NY || X < 0 || X >= NX) continue;
    int k = (Z * NY + Y) * NX + X;
    int nn = (dz != 0) + (dy != 0) + (dx != 0);
    double wg = nn == 1 ? wf : (nn == 2 ? we : wc);
    double d = xj - R[k].x, ad = fabs(d), phi = xj + R[k].x + gam * ad + eps;
    g += wg * kj * R[k].kap * d * (2 * phi - (d + gam * ad)) / (phi * phi);
  }
  return g;
}

int main(int argc, char **argv) {
  int nz = argc > 1 ? atoi(argv[1]) : 4;
  int n = nz * PLANE;
  std::vector<Rec> R(n);
  std::vector<Out> O(n);
  srand(7);
  auto rnd = []() { return (float)rand() / RAND_MAX; };
  for (int i = 0; i < n; i++) {
    R[i].x = (rnd() < 0.05f) ? 0.0f : 0.5f + rnd();
    R[i].B = rnd(); R[i].gk = rnd(); R[i].gsum = rnd() - 0.5f; R[i].s = rnd(); R[i].P = 0.1f * rnd(); R[i].kap = 0.5f + rnd();
    R[i].pad = 0;
  }
  const float M = 8, sigma = 1, alpha = 3.5f, beta = 0.2f, eps = 1e-3f, gam = 2, wf = 1, we = 0.70710678f, wc = 0.57735027f;
  int bad = 0; double maxrel = 0;
  for (int mode = 0; mode < 2; mode++) {
    RecPort ahead(R.data(), n * sizeof(Rec));
    OutPort out(O.data(), n * sizeof(Out));
    psv_update(ahead, out, nz, mode, M, sigma, alpha, beta, eps, gam, wf, we, wc, 1);
    for (int z = 0; z < nz; z++) for (int y = 0; y < NY; y++) for (int x = 0; x < NX; x++) {
      int i = (z * NY + y) * NX + x;
      double g = ref_grad(R, nz, z, y, x, eps, gam, wf, we, wc);
      double pr = R[i].s + beta * g, a, b;
      if (mode == 0) { double xn = R[i].x + alpha * R[i].P * (M * (R[i].B - R[i].gk) - sigma * pr + R[i].gsum); a = xn > 0 ? xn : 0; b = 0; }
      else { a = R[i].B - pr / M; b = R[i].gsum + a; }
      double e = fabs(O[i].a - a) / (fabs(a) + 1e-3) + fabs(O[i].b - b) / (fabs(b) + 1e-3);
      if (e > maxrel) maxrel = e;
      if (e > 1e-4) bad++;
    }
  }
  printf("voxels %d x 2 modes, max rel err %.3e, bad %d\n", n, maxrel, bad);
  // dump for the board test
  FILE *f = fopen("rec.bin", "wb"); fwrite(R.data(), sizeof(Rec), n, f); fclose(f);
  { RecPort a2(R.data(), n * sizeof(Rec)); OutPort o2(O.data(), n * sizeof(Out));
    psv_update(a2, o2, nz, 0, M, sigma, alpha, beta, eps, gam, wf, we, wc, 2); }
  f = fopen("expect_out.bin", "wb"); fwrite(O.data(), sizeof(Out), n, f); fclose(f);
  printf(bad ? "FAILED\n" : "PASSED\n");
  return bad ? 1 : 0;
}
#endif
