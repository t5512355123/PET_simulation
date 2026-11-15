// Event-driven Joseph projector lane for online BSREM (Intel HLS, Stratix 10).
// One call processes a batch of events (nonzero bins of one subset):
//   loop 1: forward projection F_e of every event, s_e = mw*y / (mw*F_e + a)
//   loop 2: back projection of s_e into an accumulator (two copies, alternating by event)
// Image and accumulators are split into 8 banks by (x&1, y&1, z&1) so the 4 bilinear
// neighbours of a Joseph sample are always in 4 different banks (conflict-free, II=1).
#include "HLS/hls.h"
#include "HLS/stdio.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

#ifndef NX
#define NX 96
#endif
#ifndef NY
#define NY 96
#endif
#ifndef NZ
#define NZ 48
#endif
#ifndef MAXEV
#define MAXEV 65536
#endif
#define NB 8
#define HX (NX / 2)
#define HY (NY / 2)
#define HZ (NZ / 2)
#define BANKSZ (HX * HY * HZ)
#define FRAC 16

struct Ev {            // 32 bytes
  short i0;            // first plane along the dominant axis
  short n_axis;        // bit 15: dominant axis (0 = x, 1 = y); bits 0..14: number of steps
  int u0, v0, du, dv;  // Q16.16 voxel coordinates at the first plane and per-plane increments
  float mw;            // m * w (w = path length per plane)
  float y;             // counts
  float a;             // additive term
};

// sample weights and bank addresses of one Joseph step
static inline void step_geom(int axis, int p, int u, int v, int addr[NB], float wt[NB]) {
  int iu = u >> FRAC, iv = v >> FRAC;
  float fu = (float)(u & ((1 << FRAC) - 1)) * (1.0f / (1 << FRAC));
  float fv = (float)(v & ((1 << FRAC) - 1)) * (1.0f / (1 << FRAC));
#pragma unroll
  for (int b = 0; b < NB; b++) {
    int px = b & 1, py = (b >> 1) & 1, pz = (b >> 2) & 1;
    int pd = axis ? py : px;   // parity of the dominant coordinate for this bank
    int pu = axis ? px : py;   // parity of the in-plane transaxial coordinate
    int cu = ((iu & 1) == pu) ? iu : iu + 1;
    float wu = (cu == iu) ? (1.0f - fu) : fu;
    int cz = ((iv & 1) == pz) ? iv : iv + 1;
    float wz = (cz == iv) ? (1.0f - fv) : fv;
    int nu = axis ? NX : NY;
    bool ok = ((p & 1) == pd) && p >= 0 && p < (axis ? NY : NX) && cu >= 0 && cu < nu && cz >= 0 && cz < NZ;
    int x = axis ? cu : p, y = axis ? p : cu;
    int xc = ok ? x : px, yc = ok ? y : py, zc = ok ? cz : pz;  // clamp to a valid address in this bank
    addr[b] = (((xc >> 1) * HY + (yc >> 1)) * HZ + (zc >> 1));
    wt[b] = ok ? wu * wz : 0.0f;
  }
}

#ifndef IOCHUNK
#define IOCHUNK 65536
#endif
// on-chip state (persists across calls): image and two accumulator copies, 8 banks each
static float IMG[NB][BANKSZ];
static float ACC[2][NB][BANKSZ];

// mode 0: load IOCHUNK-sized slice of the image (banked flat index off..off+cnt-1) from io
// mode 1: process nev events (forward, ratio, back projection)
// mode 2: write ACC[0]+ACC[1] for flat index off..off+cnt-1 into io and clear it
component void ev_lane(
    hls_avalon_slave_memory_argument(MAXEV * sizeof(Ev)) Ev *ev,
    hls_avalon_slave_memory_argument(MAXEV * sizeof(float)) float *s_out,
    hls_avalon_slave_memory_argument(IOCHUNK * sizeof(float)) float *io,
    int mode, int nev, int off, int cnt) {
  if (mode == 0) {
#pragma ivdep
    for (int i = 0; i < cnt; i++) {
      int fi = off + i, ad = fi >> 3, bb = fi & 7;
      float v = io[i];
#pragma unroll
      for (int b = 0; b < NB; b++)
        if (b == bb) IMG[b][ad] = v;
    }
    return;
  }
  if (mode == 2) {
#pragma ivdep
    for (int i = 0; i < cnt; i++) {
      int fi = off + i, ad = fi >> 3, bb = fi & 7;
      float sum = 0.0f;
#pragma unroll
      for (int b = 0; b < NB; b++) {
        if (b == bb) {
          sum = ACC[0][b][ad] + ACC[1][b][ad];
          ACC[0][b][ad] = 0.0f;
          ACC[1][b][ad] = 0.0f;
        }
      }
      io[i] = sum;
    }
    return;
  }
  // ---- loop 1: forward projection (outer: events, inner: Joseph steps) ----
  for (int e = 0; e < nev; e++) {
    Ev cur = ev[e];
    int axis = (cur.n_axis >> 15) & 1, n = cur.n_axis & 0x7fff;
    float F = 0.0f;
#pragma ii 1
    for (int k = 0; k < n; k++) {
      int addr[NB];
      float wt[NB];
      step_geom(axis, cur.i0 + k, cur.u0 + k * cur.du, cur.v0 + k * cur.dv, addr, wt);
      float val = 0.0f;
#pragma unroll
      for (int b = 0; b < NB; b++) val += wt[b] * IMG[b][addr[b]];
      F += val;
    }
    float yh = cur.mw * F + cur.a;
    s_out[e] = (yh > 0.0f) ? cur.mw * cur.y / yh : 0.0f;
  }
  // ---- loop 2: back projection into ACC[e & 1] ----
#pragma ivdep array(ACC)
  for (int e = 0; e < nev; e++) {
    Ev cur = ev[e];
    int axis = (cur.n_axis >> 15) & 1, n = cur.n_axis & 0x7fff;
    float s = s_out[e];
    int c = e & 1;
#pragma ivdep array(ACC)
#pragma ii 1
    for (int k = 0; k < n; k++) {
      int addr[NB];
      float wt[NB];
      step_geom(axis, cur.i0 + k, cur.u0 + k * cur.du, cur.v0 + k * cur.dv, addr, wt);
#pragma unroll
      for (int cc = 0; cc < 2; cc++) {
#pragma unroll
        for (int b = 0; b < NB; b++) {
          if (cc == c) ACC[cc][b][addr[b]] += s * wt[b];
        }
      }
    }
  }
}

#ifndef NO_TESTBENCH
// ---------------- testbench: synthetic phantom, double-precision reference ----------------
static inline int bidx(int x, int y, int z) {  // flat index in the banked layout used by img
  int b = (x & 1) | ((y & 1) << 1) | ((z & 1) << 2);
  return ((((x >> 1) * HY + (y >> 1)) * HZ + (z >> 1)) << 3) | b;
}
static double ref_val(const double *im, int axis, int p, double u, double v) {
  int iu = (int)floor(u), iv = (int)floor(v);
  double fu = u - iu, fv = v - iv, s = 0;
  for (int du = 0; du < 2; du++)
    for (int dz = 0; dz < 2; dz++) {
      int cu = iu + du, cz = iv + dz;
      int x = axis ? cu : p, y = axis ? p : cu;
      if (x < 0 || x >= NX || y < 0 || y >= NY || cz < 0 || cz >= NZ) continue;
      s += (du ? fu : 1 - fu) * (dz ? fv : 1 - fv) * im[(x * NY + y) * NZ + cz];
    }
  return s;
}
static void ref_back(double *bk, int axis, int p, double u, double v, double sc) {
  int iu = (int)floor(u), iv = (int)floor(v);
  double fu = u - iu, fv = v - iv;
  for (int du = 0; du < 2; du++)
    for (int dz = 0; dz < 2; dz++) {
      int cu = iu + du, cz = iv + dz;
      int x = axis ? cu : p, y = axis ? p : cu;
      if (x < 0 || x >= NX || y < 0 || y >= NY || cz < 0 || cz >= NZ) continue;
      bk[(x * NY + y) * NZ + cz] += sc * (du ? fu : 1 - fu) * (dz ? fv : 1 - fv);
    }
}
static unsigned long long rs = 88172645463325252ULL;
static double urand() { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return (rs >> 11) * (1.0 / 9007199254740992.0); }
static int poisson(double l) { double L = exp(-l), p = 1; int k = 0; do { k++; p *= urand(); } while (p > L); return k - 1; }

// build one event for a LOR between two points on a cylinder (voxel units, image centred)
static bool make_event(double ph, double s, double z1, double z2, double R, Ev &e) {
  double cx = (NX - 1) / 2.0, cy = (NY - 1) / 2.0;
  double h = sqrt(R * R - s * s);
  double x1 = cx + s * cos(ph) - h * sin(ph), y1 = cy + s * sin(ph) + h * cos(ph);
  double x2 = cx + s * cos(ph) + h * sin(ph), y2 = cy + s * sin(ph) - h * cos(ph);
  double dx = x2 - x1, dy = y2 - y1, dz = z2 - z1;
  int axis = fabs(dy) > fabs(dx) ? 1 : 0;
  double dd = axis ? dy : dx;
  if (dd < 0) { double t; t = x1; x1 = x2; x2 = t; t = y1; y1 = y2; y2 = t; t = z1; z1 = z2; z2 = t; dx = -dx; dy = -dy; dz = -dz; dd = -dd; }
  double du = (axis ? dx : dy) / dd, dv = dz / dd;
  double d0 = axis ? y1 : x1, u1 = axis ? x1 : y1;
  int np = axis ? NY : NX;
  int i0 = (int)ceil(d0), i1 = (int)floor(d0 + dd);
  if (i0 < 0) i0 = 0;
  if (i1 > np - 1) i1 = np - 1;
  // clip to planes where the sample is inside the in-plane range
  int nu = axis ? NX : NY;
  int a = -1, b = -1;
  for (int p = i0; p <= i1; p++) {
    double u = u1 + (p - d0) * du, v = z1 + (p - d0) * dv;
    if (u > -1 && u < nu && v > -1 && v < NZ) { if (a < 0) a = p; b = p; }
  }
  if (a < 0) return false;
  int n = b - a + 1;
  if (n < 16) n = 16;  // pad very short rays (zero-weight steps outside the image) for the RMW hazard rule
  double u0 = u1 + (a - d0) * du, v0 = z1 + (a - d0) * dv;
  e.i0 = (short)a;
  e.n_axis = (short)(n | (axis << 15));
  e.u0 = (int)lround(u0 * 65536.0);
  e.v0 = (int)lround(v0 * 65536.0);
  e.du = (int)lround(du * 65536.0);
  e.dv = (int)lround(dv * 65536.0);
  e.mw = (float)sqrt(1 + du * du + dv * dv);  // m = 1, voxel size 1
  return true;
}

int main(int argc, char **argv) {
  int NEV = argc > 1 ? atoi(argv[1]) : 4000;
  if (NEV > MAXEV) NEV = MAXEV;
  static double phantom[NX * NY * NZ], back_ref[NX * NY * NZ];
  static float img[NB * BANKSZ], acc[NB * BANKSZ], s_out[MAXEV];
  static Ev ev[MAXEV];
  double cx = (NX - 1) / 2.0, cy = (NY - 1) / 2.0, cz = (NZ - 1) / 2.0;
  for (int x = 0; x < NX; x++)
    for (int y = 0; y < NY; y++)
      for (int z = 0; z < NZ; z++) {
        double r = hypot(x - cx, y - cy), val = r < 0.42 * NX ? 1.0 : 0.0;
        if (hypot(x - cx - 12, y - cy) < 6 && fabs(z - cz) < 6) val = 4.0;
        if (hypot(x - cx + 10, y - cy + 10) < 4 && fabs(z - cz) < 4) val = 0.0;
        phantom[(x * NY + y) * NZ + z] = val;
        img[bidx(x, y, z)] = (float)val;
      }
  // events: random LORs, expected counts from the reference projector, Poisson, keep y > 0
  double R = 0.75 * NX;
  int ne = 0, tries = 0;
  while (ne < NEV && tries < 50 * NEV) {
    tries++;
    Ev e;
    double ph = urand() * M_PI, s = (urand() - 0.5) * 0.9 * NX;
    double zc = urand() * (NZ - 1), dzr = (urand() - 0.5) * 0.4 * NZ;
    if (!make_event(ph, s, zc - dzr / 2, zc + dzr / 2, R, e)) continue;
    int axis = (e.n_axis >> 15) & 1, n = e.n_axis & 0x7fff;
    double F = 0;
    for (int k = 0; k < n; k++) F += ref_val(phantom, axis, e.i0 + k, (e.u0 + (double)k * e.du) / 65536.0, (e.v0 + (double)k * e.dv) / 65536.0);
    e.a = 0.2f;
    int yv = poisson(0.05 * (e.mw * F + e.a));
    if (yv <= 0) continue;
    e.y = (float)yv;
    ev[ne++] = e;
  }
  static float io[IOCHUNK];
  for (int off = 0; off < NB * BANKSZ; off += IOCHUNK) {
    int cnt = (NB * BANKSZ - off) < IOCHUNK ? (NB * BANKSZ - off) : IOCHUNK;
    memcpy(io, img + off, cnt * sizeof(float));
    ev_lane(ev, s_out, io, 0, 0, off, cnt);
  }
  ev_lane(ev, s_out, io, 1, ne, 0, 0);
  for (int off = 0; off < NB * BANKSZ; off += IOCHUNK) {
    int cnt = (NB * BANKSZ - off) < IOCHUNK ? (NB * BANKSZ - off) : IOCHUNK;
    ev_lane(ev, s_out, io, 2, 0, off, cnt);
    memcpy(acc + off, io, cnt * sizeof(float));
  }
  // reference
  memset(back_ref, 0, sizeof(back_ref));
  double max_s_err = 0, max_b_err = 0, max_b = 0;
  long long steps = 0;
  for (int i = 0; i < ne; i++) {
    Ev &e = ev[i];
    int axis = (e.n_axis >> 15) & 1, n = e.n_axis & 0x7fff;
    steps += n;
    double F = 0;
    for (int k = 0; k < n; k++) F += ref_val(phantom, axis, e.i0 + k, (e.u0 + (double)k * e.du) / 65536.0, (e.v0 + (double)k * e.dv) / 65536.0);
    double yh = e.mw * F + e.a, s = e.mw * e.y / yh;
    max_s_err = fmax(max_s_err, fabs(s - s_out[i]) / s);
    for (int k = 0; k < n; k++) ref_back(back_ref, axis, e.i0 + k, (e.u0 + (double)k * e.du) / 65536.0, (e.v0 + (double)k * e.dv) / 65536.0, s);
  }
  for (int x = 0; x < NX; x++)
    for (int y = 0; y < NY; y++)
      for (int z = 0; z < NZ; z++) {
        int fi = bidx(x, y, z), b = fi & 7, ad = fi >> 3;
        double hw = (double)acc[fi];
        double rf = back_ref[(x * NY + y) * NZ + z];
        max_b = fmax(max_b, fabs(rf));
        max_b_err = fmax(max_b_err, fabs(hw - rf));
      }
  printf("events %d (tries %d), steps %lld (%.1f per event)\n", ne, tries, steps, (double)steps / ne);
  if (getenv("DUMP")) {  // files for the on-board test: inputs and the expected outputs of this emulation run
    FILE *f;
    f = fopen("ev.bin", "wb"); fwrite(ev, sizeof(Ev), ne, f); fclose(f);
    f = fopen("img.bin", "wb"); fwrite(img, sizeof(float), NB * BANKSZ, f); fclose(f);
    f = fopen("expect_s.bin", "wb"); fwrite(s_out, sizeof(float), ne, f); fclose(f);
    f = fopen("expect_acc.bin", "wb"); fwrite(acc, sizeof(float), NB * BANKSZ, f); fclose(f);
    f = fopen("meta.txt", "w"); fprintf(f, "nev %d\nsteps %lld\nvoxels %d\n", ne, steps, NB * BANKSZ); fclose(f);
    printf("dumped ev.bin img.bin expect_s.bin expect_acc.bin\n");
  }
  printf("max rel err forward ratio s: %.3e\n", max_s_err);
  printf("max abs err back / max back: %.3e\n", max_b_err / max_b);
  bool ok = max_s_err < 1e-4 && max_b_err / max_b < 1e-4;
  printf(ok ? "PASSED\n" : "FAILED\n");
  return ok ? 0 : 1;
}
#endif
