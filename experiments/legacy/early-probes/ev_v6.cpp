// v5: event producer (component) -> step stream -> flat compute engine (task), II=1, no per-event pipeline drain.
// Back projection: single accumulator, predicated read-modify-write, hazards removed by host-side bubble scheduling
// (no two events touch the same voxel within HAZ consecutive steps).
#include "HLS/hls.h"
#include "HLS/stdio.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <vector>

#ifndef NX
#define NX 64
#endif
#ifndef NY
#define NY 64
#endif
#ifndef NZ
#define NZ 32
#endif
#ifndef MAXEV
#define MAXEV 4096
#endif
#ifndef IOCHUNK
#define IOCHUNK 16384
#endif
#ifndef HAZ
#define HAZ 210
#endif
#define NB 8
#define HX (NX / 2)
#define HY (NY / 2)
#define HZ (NZ / 2)
#define BANKSZ (HX * HY * HZ)
#define FRAC 16

struct Ev {            // 32 bytes (same as v1-v4)
  short i0;
  short n_axis;        // bit 15: axis; bits 0..14: steps
  int u0, v0, du, dv;
  float mw, y, a;
};
struct StepF { int u, v; short p; unsigned char axis, last; };
struct EvP { float mw, y, a; };
struct StepB { int u, v; short p; unsigned char axis, pad; float s; };

#ifndef LANES
#define LANES 4
#endif
struct EvB { Ev e; float s; };

static inline void step_geom(int axis, int p, int u, int v, int addr[NB], float wt[NB], bool ok[NB]) {
  int iu = u >> FRAC, iv = v >> FRAC;
  float fu = (float)(u & ((1 << FRAC) - 1)) * (1.0f / (1 << FRAC));
  float fv = (float)(v & ((1 << FRAC) - 1)) * (1.0f / (1 << FRAC));
#pragma unroll
  for (int b = 0; b < NB; b++) {
    int px = b & 1, py = (b >> 1) & 1, pz = (b >> 2) & 1;
    int pd = axis ? py : px;
    int pu = axis ? px : py;
    int cu = ((iu & 1) == pu) ? iu : iu + 1;
    float wu = (cu == iu) ? (1.0f - fu) : fu;
    int cz = ((iv & 1) == pz) ? iv : iv + 1;
    float wz = (cz == iv) ? (1.0f - fv) : fv;
    int nu = axis ? NX : NY;
    bool o = ((p & 1) == pd) && p >= 0 && p < (axis ? NY : NX) && cu >= 0 && cu < nu && cz >= 0 && cz < NZ;
    int x = axis ? cu : p, y = axis ? p : cu;
    int xc = o ? x : px, yc = o ? y : py, zc = o ? cz : pz;
    addr[b] = (((xc >> 1) * HY + (yc >> 1)) * HZ + (zc >> 1));
    wt[b] = o ? wu * wz : 0.0f;
    ok[b] = o;
  }
}



#define DEFINE_LANE(L)                                                                                     \
  ihc::stream<Ev, ihc::buffer<64>> evq##L;                                                                 \
  ihc::stream<EvB, ihc::buffer<64>> evb##L;                                                                \
  ihc::stream<StepF, ihc::buffer<256>> sf##L;                                                              \
  ihc::stream<EvP, ihc::buffer<64>> se##L;                                                                 \
  ihc::stream<float, ihc::buffer<MAXEV>> ss##L;                                                            \
  ihc::stream<StepB, ihc::buffer<256>> sb##L;                                                              \
  ihc::stream<float, ihc::buffer<256>> lin##L;                                                             \
  ihc::stream<float, ihc::buffer<256>> lout##L;                                                            \
  void prod_f##L(int nev) {                                                                                \
    for (int e = 0; e < nev; e++) {                                                                        \
      Ev c = evq##L.read();                                                                                \
      int axis = (c.n_axis >> 15) & 1, n = c.n_axis & 0x7fff;                                              \
      EvP q; q.mw = c.mw; q.y = c.y; q.a = c.a;                                                             \
      se##L.write(q);                                                                                      \
      for (int k = 0; k < n; k++) {                                                                        \
        StepF st; st.u = c.u0 + k * c.du; st.v = c.v0 + k * c.dv; st.p = (short)(c.i0 + k);                \
        st.axis = (unsigned char)axis; st.last = (k == n - 1);                                             \
        sf##L.write(st);                                                                                   \
      }                                                                                                    \
    }                                                                                                      \
  }                                                                                                        \
  void prod_b##L(int nev) {                                                                                \
    for (int e = 0; e < nev; e++) {                                                                        \
      EvB cb = evb##L.read();                                                                              \
      Ev c = cb.e;                                                                                         \
      int axis = (c.n_axis >> 15) & 1, n = c.n_axis & 0x7fff;                                              \
      for (int k = 0; k < n; k++) {                                                                        \
        StepB st; st.u = c.u0 + k * c.du; st.v = c.v0 + k * c.dv; st.p = (short)(c.i0 + k);                \
        st.axis = (unsigned char)axis; st.pad = 0; st.s = cb.s;                                            \
        sb##L.write(st);                                                                                   \
      }                                                                                                    \
    }                                                                                                      \
  }                                                                                                        \
  void eng##L(int mode, int total, int off) {                                                              \
    static float IMG[NB][BANKSZ];                                                                          \
    static float ACC[NB][BANKSZ];                                                                          \
    if (mode == 0) {                                                                                       \
      _Pragma("ivdep array(IMG)")                                                                          \
      for (int i = 0; i < total; i++) {                                                                    \
        int fi = off + i, ad = fi >> 3, bb = fi & 7;                                                       \
        float v = lin##L.read();                                                                           \
        _Pragma("unroll") for (int b = 0; b < NB; b++) if (b == bb) IMG[b][ad] = v;                        \
      }                                                                                                    \
    } else if (mode == 2) {                                                                                \
      _Pragma("ivdep array(ACC)")                                                                          \
      for (int i = 0; i < total; i++) {                                                                    \
        int fi = off + i, ad = fi >> 3, bb = fi & 7;                                                       \
        float sum = 0.0f;                                                                                  \
        _Pragma("unroll") for (int b = 0; b < NB; b++) if (b == bb) { sum = ACC[b][ad]; ACC[b][ad] = 0.0f; } \
        lout##L.write(sum);                                                                                \
      }                                                                                                    \
    } else if (mode == 1) {                                                                                \
      float F = 0.0f;                                                                                      \
      bool rst = true;                                                                                     \
      for (int t = 0; t < total; t++) {                                                                    \
        StepF st = sf##L.read();                                                                           \
        int addr[NB]; float wt[NB]; bool ok[NB];                                                           \
        step_geom(st.axis, st.p, st.u, st.v, addr, wt, ok);                                                \
        float val = 0.0f;                                                                                  \
        _Pragma("unroll") for (int b = 0; b < NB; b++) val += wt[b] * IMG[b][addr[b]];                     \
        F = (rst ? 0.0f : F) + val;                                                                        \
        rst = st.last;                                                                                     \
        if (st.last) {                                                                                     \
          EvP q = se##L.read();                                                                            \
          float yh = q.mw * F + q.a;                                                                       \
          ss##L.write((yh > 0.0f) ? q.mw * q.y / yh : 0.0f);                                               \
        }                                                                                                  \
      }                                                                                                    \
    } else {                                                                                               \
      _Pragma("ivdep array(ACC)")                                                                          \
      for (int t = 0; t < total; t++) {                                                                    \
        StepB st = sb##L.read();                                                                           \
        int addr[NB]; float wt[NB]; bool ok[NB];                                                           \
        step_geom(st.axis, st.p, st.u, st.v, addr, wt, ok);                                                \
        _Pragma("unroll") for (int b = 0; b < NB; b++) if (ok[b]) ACC[b][addr[b]] += st.s * wt[b];         \
      }                                                                                                    \
    }                                                                                                      \
  }

DEFINE_LANE(0)
#if LANES > 1
DEFINE_LANE(1)
#endif
#if LANES > 2
DEFINE_LANE(2)
DEFINE_LANE(3)
#endif

#if LANES > 1
#define IF1(x) x
#else
#define IF1(x)
#endif
#if LANES > 2
#define IF2(x) x
#else
#define IF2(x)
#endif
#define FOR_LANES(X) X(0) IF1(X(1)) IF2(X(2) X(3))

#define L0(L) ihc::launch<eng##L>(0, cnt, off);
#define W0(L) lin##L.write(v);
#define C0(L) ihc::collect<eng##L>();
#define L2(L) ihc::launch<eng##L>(2, cnt, off);
#define R2(L) sum += lout##L.read();
#define L1(L) ihc::launch<eng##L>(1, tot[L], 0); ihc::launch<prod_f##L>(nl[L]);
#define F1(LL) if (L == LL) evq##LL.write(c);
#define C1(L) ihc::collect<prod_f##L>(); ihc::collect<eng##L>();
#define S1(LL) if (L == LL) s = ss##LL.read();
#define L3(L) ihc::launch<eng##L>(3, tot[L], 0); ihc::launch<prod_b##L>(nl[L]);
#define B1(LL) if (L == LL) evb##LL.write(cb);
#define C3(L) ihc::collect<prod_b##L>(); ihc::collect<eng##L>();

// lanes take events round-robin (event e -> lane e % LANES); for mode 1, io[0..LANES-1] holds each lane's total steps
hls_avalon_slave_component component void ev_lane(
    hls_avalon_slave_memory_argument(MAXEV * sizeof(Ev)) Ev *ev,
    hls_avalon_slave_memory_argument(MAXEV * sizeof(float)) float *s_out,
    hls_avalon_slave_memory_argument(IOCHUNK * sizeof(float)) float *io,
    hls_avalon_slave_register_argument int mode, hls_avalon_slave_register_argument int nev,
    hls_avalon_slave_register_argument int off, hls_avalon_slave_register_argument int cnt,
    hls_avalon_slave_register_argument int rep) {
  if (mode == 0) {
    FOR_LANES(L0)
    for (int i = 0; i < cnt; i++) {
      float v = io[i];
      FOR_LANES(W0)
    }
    FOR_LANES(C0)
    return;
  }
  if (mode == 2) {
    FOR_LANES(L2)
    for (int i = 0; i < cnt; i++) {
      float sum = 0.0f;
      FOR_LANES(R2)
      io[i] = sum;
    }
    FOR_LANES(C0)
    return;
  }
  int tot[LANES], nl[LANES];
#pragma unroll
  for (int L = 0; L < LANES; L++) {
    tot[L] = (int)io[L];
    nl[L] = nev / LANES + ((L < nev % LANES) ? 1 : 0);
  }
  for (int r = 0; r < rep; r++) {
    FOR_LANES(L1)
    for (int e = 0; e < nev; e++) {
      Ev c = ev[e];
      int L = e % LANES;
      FOR_LANES(F1)
    }
    FOR_LANES(C1)
    for (int e = 0; e < nev; e++) {
      int L = e % LANES;
      float s = 0.0f;
      FOR_LANES(S1)
      s_out[e] = s;
    }
    FOR_LANES(L3)
    for (int e = 0; e < nev; e++) {
      EvB cb;
      cb.e = ev[e];
      cb.s = s_out[e];
      int L = e % LANES;
      FOR_LANES(B1)
    }
    FOR_LANES(C3)
  }
}

#ifndef NO_TESTBENCH
// ---------------- host side: event generation, bubble scheduling, double reference ----------------
static inline int bidx(int x, int y, int z) {
  int b = (x & 1) | ((y & 1) << 1) | ((z & 1) << 2);
  return ((((x >> 1) * HY + (y >> 1)) * HZ + (z >> 1)) << 3) | b;
}
static void ref_step(int axis, int p, double u, double v, int vox[4], double w[4], int &nv) {
  int iu = (int)floor(u), iv = (int)floor(v);
  double fu = u - iu, fv = v - iv;
  nv = 0;
  for (int du = 0; du < 2; du++)
    for (int dz = 0; dz < 2; dz++) {
      int cu = iu + du, cz = iv + dz;
      int x = axis ? cu : p, y = axis ? p : cu;
      if (x < 0 || x >= NX || y < 0 || y >= NY || cz < 0 || cz >= NZ) continue;
      vox[nv] = (x * NY + y) * NZ + cz;
      w[nv] = (du ? fu : 1 - fu) * (dz ? fv : 1 - fv);
      nv++;
    }
}
static unsigned long long rs = 88172645463325252ULL;
static double urand() { rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17; return (rs >> 11) * (1.0 / 9007199254740992.0); }
static int poisson(double l) { double L = exp(-l), p = 1; int k = 0; do { k++; p *= urand(); } while (p > L); return k - 1; }

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
  int np = axis ? NY : NX, nu = axis ? NX : NY;
  int i0 = (int)ceil(d0), i1 = (int)floor(d0 + dd);
  if (i0 < 0) i0 = 0;
  if (i1 > np - 1) i1 = np - 1;
  int a = -1, b = -1;
  for (int p = i0; p <= i1; p++) {
    double u = u1 + (p - d0) * du, v = z1 + (p - d0) * dv;
    if (u > -1 && u < nu && v > -1 && v < NZ) { if (a < 0) a = p; b = p; }
  }
  if (a < 0) return false;
  double u0 = u1 + (a - d0) * du, v0 = z1 + (a - d0) * dv;
  e.i0 = (short)a;
  e.n_axis = (short)((b - a + 1) | (axis << 15));
  e.u0 = (int)lround(u0 * 65536.0);
  e.v0 = (int)lround(v0 * 65536.0);
  e.du = (int)lround(du * 65536.0);
  e.dv = (int)lround(dv * 65536.0);
  e.mw = (float)sqrt(1 + du * du + dv * dv);
  return true;
}

// voxels written by one step in hardware (all ok banks), as flat banked indices
static int hw_voxels(const Ev &e, int k, int out[NB]) {
  int axis = (e.n_axis >> 15) & 1;
  int addr[NB];
  float wt[NB];
  bool ok[NB];
  step_geom(axis, e.i0 + k, e.u0 + k * e.du, e.v0 + k * e.dv, addr, wt, ok);
  int n = 0;
  for (int b = 0; b < NB; b++)
    if (ok[b]) out[n++] = (addr[b] << 3) | b;
  return n;
}

// order events greedily so that no two different events touch the same voxel within HAZ steps;
// pick, from a window of pending events, one that needs no bubbles; insert bubbles only when none fits
static std::vector<Ev> schedule(const std::vector<Ev> &in, long long &bubbles) {
  const int WIN = 64;
  std::vector<Ev> out;
  std::vector<long long> last_t(NB * BANKSZ, -1000000000LL);
  std::vector<int> pend;
  size_t next = 0;
  long long t = 0;
  bubbles = 0;
  int vv[NB];
  auto need = [&](const Ev &e) {
    int n = e.n_axis & 0x7fff;
    long long shift = 0;
    for (int k = 0; k < n; k++) {
      int nv = hw_voxels(e, k, vv);
      for (int j = 0; j < nv; j++) {
        long long gap = (t + k) - last_t[vv[j]];
        if (gap < HAZ && HAZ - gap > shift) shift = HAZ - gap;
      }
    }
    return shift;
  };
  while (next < in.size() || !pend.empty()) {
    while ((int)pend.size() < WIN && next < in.size()) pend.push_back((int)next++);
    int best = -1;
    long long bs = 1LL << 60;
    for (size_t i = 0; i < pend.size(); i++) {
      long long sh = need(in[pend[i]]);
      if (sh < bs) { bs = sh; best = (int)i; }
      if (sh == 0) break;
    }
    const Ev &e = in[pend[best]];
    if (bs > 0) {
      Ev d;
      memset(&d, 0, sizeof(d));
      d.i0 = -1000;
      d.n_axis = (short)bs;
      out.push_back(d);
      t += bs;
      bubbles += bs;
    }
    int n = e.n_axis & 0x7fff;
    for (int k = 0; k < n; k++) {
      int nv = hw_voxels(e, k, vv);
      for (int j = 0; j < nv; j++) last_t[vv[j]] = t + k;
    }
    out.push_back(e);
    t += n;
    pend.erase(pend.begin() + best);
  }
  return out;
}

int main(int argc, char **argv) {
  int NEVR = argc > 1 ? atoi(argv[1]) : 3500;
  static double phantom[NX * NY * NZ], back_ref[NX * NY * NZ];
  static float img[NB * BANKSZ], acc[NB * BANKSZ], s_out[MAXEV], io[IOCHUNK];
  static Ev ev[MAXEV];
  double cx = (NX - 1) / 2.0, cy = (NY - 1) / 2.0, cz = (NZ - 1) / 2.0;
  for (int x = 0; x < NX; x++)
    for (int y = 0; y < NY; y++)
      for (int z = 0; z < NZ; z++) {
        double r = hypot(x - cx, y - cy), val = r < 0.42 * NX ? 1.0 : 0.0;
        if (hypot(x - cx - 8, y - cy) < 4 && fabs(z - cz) < 4) val = 4.0;
        phantom[(x * NY + y) * NZ + z] = val;
        img[bidx(x, y, z)] = (float)val;
      }
  std::vector<Ev> raw;
  double R = 0.75 * NX;
  int tries = 0;
  while ((int)raw.size() < NEVR && tries < 50 * NEVR) {
    tries++;
    Ev e;
    double ph = urand() * M_PI, s = (urand() - 0.5) * 0.9 * NX;
    double zc = urand() * (NZ - 1), dzr = (urand() - 0.5) * 0.4 * NZ;
    if (!make_event(ph, s, zc - dzr / 2, zc + dzr / 2, R, e)) continue;
    int axis = (e.n_axis >> 15) & 1, n = e.n_axis & 0x7fff;
    double F = 0, w[4];
    int vx[4], nv;
    for (int k = 0; k < n; k++) {
      ref_step(axis, e.i0 + k, (e.u0 + (double)k * e.du) / 65536.0, (e.v0 + (double)k * e.dv) / 65536.0, vx, w, nv);
      for (int j = 0; j < nv; j++) F += w[j] * phantom[vx[j]];
    }
    e.a = 0.2f;
    int yv = poisson(0.05 * (e.mw * F + e.a));
    if (yv <= 0) continue;
    e.y = (float)yv;
    raw.push_back(e);
  }
  long long bubbles = 0;
  std::vector<std::vector<Ev>> per(LANES), sl(LANES);
  for (size_t i = 0; i < raw.size(); i++) per[i % LANES].push_back(raw[i]);
  long long lane_steps[LANES];
  for (int L = 0; L < LANES; L++) {
    long long bb;
    sl[L] = schedule(per[L], bb);
    bubbles += bb;
  }
  size_t mx = 0;
  for (int L = 0; L < LANES; L++) mx = sl[L].size() > mx ? sl[L].size() : mx;
  std::vector<Ev> sch;
  for (int L = 0; L < LANES; L++) lane_steps[L] = 0;
  for (size_t i = 0; i < mx; i++)
    for (int L = 0; L < LANES; L++) {
      Ev x;
      if (i < sl[L].size()) x = sl[L][i];
      else { memset(&x, 0, sizeof(x)); x.i0 = -1000; x.n_axis = 1; }
      lane_steps[L] += x.n_axis & 0x7fff;
      sch.push_back(x);
    }
  int ne = (int)sch.size();
  if (ne > MAXEV) { printf("too many events after scheduling: %d\n", ne); return 1; }
  long long steps = 0, real_steps = 0, maxlane = 0;
  for (int i = 0; i < ne; i++) { ev[i] = sch[i]; steps += sch[i].n_axis & 0x7fff; }
  for (auto &e : raw) real_steps += e.n_axis & 0x7fff;
  for (int L = 0; L < LANES; L++) maxlane = lane_steps[L] > maxlane ? lane_steps[L] : maxlane;
  printf("events %zu (%d after scheduling), lanes %d, real steps %lld, bubbles %lld, max lane steps %lld (balance %.3f)\n", raw.size(), ne, LANES,
         real_steps, bubbles, maxlane, (double)real_steps / LANES / maxlane);
  for (int off = 0; off < NB * BANKSZ; off += IOCHUNK) {
    int cnt = (NB * BANKSZ - off) < IOCHUNK ? (NB * BANKSZ - off) : IOCHUNK;
    memcpy(io, img + off, cnt * sizeof(float));
    ev_lane(ev, s_out, io, 0, 0, off, cnt, 1);
  }
  for (int L = 0; L < LANES; L++) io[L] = (float)lane_steps[L];
  ev_lane(ev, s_out, io, 1, ne, 0, 0, 1);
  for (int off = 0; off < NB * BANKSZ; off += IOCHUNK) {
    int cnt = (NB * BANKSZ - off) < IOCHUNK ? (NB * BANKSZ - off) : IOCHUNK;
    ev_lane(ev, s_out, io, 2, 0, off, cnt, 1);
    memcpy(acc + off, io, cnt * sizeof(float));
  }
  // reference in double (dummy events have y = 0 and touch nothing)
  memset(back_ref, 0, sizeof(back_ref));
  double max_s_err = 0;
  for (int i = 0; i < ne; i++) {
    Ev &e = ev[i];
    if (e.i0 == -1000) continue;
    int axis = (e.n_axis >> 15) & 1, n = e.n_axis & 0x7fff;
    double F = 0, w[4];
    int vx[4], nv;
    for (int k = 0; k < n; k++) {
      ref_step(axis, e.i0 + k, (e.u0 + (double)k * e.du) / 65536.0, (e.v0 + (double)k * e.dv) / 65536.0, vx, w, nv);
      for (int j = 0; j < nv; j++) F += w[j] * phantom[vx[j]];
    }
    double s = e.mw * e.y / (e.mw * F + e.a);
    max_s_err = fmax(max_s_err, fabs(s - s_out[i]) / s);
    for (int k = 0; k < n; k++) {
      ref_step(axis, e.i0 + k, (e.u0 + (double)k * e.du) / 65536.0, (e.v0 + (double)k * e.dv) / 65536.0, vx, w, nv);
      for (int j = 0; j < nv; j++) back_ref[vx[j]] += s * w[j];
    }
  }
  double max_b = 0, max_b_err = 0;
  for (int x = 0; x < NX; x++)
    for (int y = 0; y < NY; y++)
      for (int z = 0; z < NZ; z++) {
        double rf = back_ref[(x * NY + y) * NZ + z];
        max_b = fmax(max_b, fabs(rf));
        max_b_err = fmax(max_b_err, fabs(acc[bidx(x, y, z)] - rf));
      }
  printf("max rel err forward ratio s: %.3e\nmax abs err back / max back: %.3e\n", max_s_err, max_b_err / max_b);
  if (getenv("DUMP")) {
    FILE *f;
    f = fopen("ev.bin", "wb"); fwrite(ev, sizeof(Ev), ne, f); fclose(f);
    f = fopen("img.bin", "wb"); fwrite(img, sizeof(float), NB * BANKSZ, f); fclose(f);
    f = fopen("expect_s.bin", "wb"); fwrite(s_out, sizeof(float), ne, f); fclose(f);
    f = fopen("expect_acc.bin", "wb"); fwrite(acc, sizeof(float), NB * BANKSZ, f); fclose(f);
    f = fopen("meta.txt", "w"); fprintf(f, "nev %d\nsteps %lld\nvoxels %d\nreal_steps %lld\nlanes %d\nmaxlane %lld\n", ne, steps, NB * BANKSZ, real_steps, LANES, maxlane); fclose(f);
    { float ls[LANES]; for (int L = 0; L < LANES; L++) ls[L] = (float)lane_steps[L]; f = fopen("lane_steps.bin", "wb"); fwrite(ls, sizeof(float), LANES, f); fclose(f); }
    printf("dumped\n");
  }
  bool ok = max_s_err < 1e-4 && max_b_err / max_b < 1e-4;
  printf(ok ? "PASSED\n" : "FAILED\n");
  return ok ? 0 : 1;
}
#endif
