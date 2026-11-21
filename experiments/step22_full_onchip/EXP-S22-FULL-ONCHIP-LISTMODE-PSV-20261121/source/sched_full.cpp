// EXP-S18b: hazard-free token schedule for the whole D690 list (per subset, as the R2 SWSIM scheduler: window 64,
// HAZ items between read-modify-writes of the same voxel in a lane) -> DDR token stream.
// Inputs (dir): ev_hw_all.bin (prep_full.py records, 48 B), keep_all.bin (int64 event index per record),
//               subset_edges.bin (int64, M + 1 event indices), fov_rows.bin (int32 [2][201][2]).
// Outputs: tok_evw.bin (32 B EvW per token, NOP: i0 = -1000, na = bubbles, u0 = lane), tok_a.bin (float a' per token),
//          tok_rec.bin (int32 record index, -1 for NOP), subsets.txt (k, first token, tokens, events, NOPs, lane items max).
// Usage: sched_full <dir> [HAZ]
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <vector>
#include <algorithm>
#define NPL 201
#define NU 201
#define NZ 47
#define LANES 40
#define SETS 4
#define FRAC 20
#pragma pack(push, 1)
struct EvIn { short i0, na; int u0, v0, du, dv; float d0, dd, mw, y, a, pad; };
struct EvW { short i0, na; int u0, v0, du, dv; float d0, dd, mw; };
#pragma pack(pop)
template <class T> std::vector<T> readf(const char *fn) {
  std::vector<T> v; FILE *f = fopen(fn, "rb");
  if (!f) { printf("cannot open %s\n", fn); exit(1); }
  fseek(f, 0, SEEK_END); long n = ftell(f) / sizeof(T); fseek(f, 0, SEEK_SET); v.resize(n);
  if (fread(v.data(), sizeof(T), n, f) != (size_t)n) exit(1);
  fclose(f); return v;
}
static inline short local_cnt(short p, short i0, short n) {
  int k = p - i0;
  if (k >= n || p >= NPL || k < 0) return 0;
  int a = (n - 1 - k) / LANES + 1, b = (NPL - 1 - p) / LANES + 1;
  return (short)(a < b ? a : b);
}
int main(int argc, char **argv) {
  const char *dir = argv[1];
  int HAZ = argc > 2 ? atoi(argv[2]) : 16;
  char fn[1024];
  snprintf(fn, sizeof fn, "%s/ev_hw_all.bin", dir); auto ev = readf<EvIn>(fn);
  snprintf(fn, sizeof fn, "%s/keep_all.bin", dir); auto keep = readf<long long>(fn);
  snprintf(fn, sizeof fn, "%s/subset_edges.bin", dir); auto edges = readf<long long>(fn);
  snprintf(fn, sizeof fn, "%s/fov_rows.bin", dir); auto rows = readf<int>(fn);
  int ulo[2][NPL], nrow[2][NPL];
  for (int c = 0; c < 2; c++)
    for (int p = 0; p < NPL; p++) {
      int lo = rows[(c * NPL + p) * 2], hi = rows[(c * NPL + p) * 2 + 1];
      ulo[c][p] = lo < 0 ? 0 : lo >> 1;
      nrow[c][p] = lo < 0 ? 0 : (hi >> 1) - (lo >> 1) + 1;
    }
  auto inrow = [&](int c, int p, int u) { return nrow[c][p] > 0 && (u >> 1) >= ulo[c][p] && (u >> 1) < ulo[c][p] + nrow[c][p]; };
  auto lane_view = [&](const EvIn &e, int L, int &pl, int &cl) {
    int n = e.na & 0x7fff;
    int r = ((L - e.i0) % LANES + LANES) % LANES;
    pl = e.i0 + r;
    cl = local_cnt((short)pl, e.i0, (short)n);
  };
  std::vector<long long> last((size_t)2 * NPL * (NU + 1) * (NZ + 1));
  auto voxkeys = [&](const EvIn &e, int k, int p, long long *keys) {
    int c = (e.na >> 15) & 1, nk = 0;
    int uu = e.u0 + k * e.du, vv = e.v0 + k * e.dv;
    int iu = uu >> FRAC, iv = vv >> FRAC;
    for (int b = 0; b < 4; b++) {
      int cu = iu + (b & 1), cz = iv + (b >> 1);
      if (cu < 0 || cu >= NU || cz < 0 || cz >= NZ || !inrow(c, p, cu)) continue;
      keys[nk++] = (((long long)c * NPL + p) * (NU + 1) + cu) * (NZ + 1) + cz;
    }
    return nk;
  };
  long long tl[LANES];
  auto need = [&](const EvIn &e, long long nd[LANES]) {
    long long tot = 0; long long kv[4];
    for (int L = 0; L < LANES; L++) {
      nd[L] = 0;
      int pl, cl; lane_view(e, L, pl, cl);
      for (int j = 0; j < cl; j++) {
        int p = pl + LANES * j, k = p - e.i0;
        long long t = tl[L] + j / SETS;
        int nv = voxkeys(e, k, p, kv);
        for (int q = 0; q < nv; q++) { long long gap = t - last[kv[q]]; if (gap < HAZ && HAZ - gap > nd[L]) nd[L] = HAZ - gap; }
      }
      tot += nd[L];
    }
    return tot;
  };
  snprintf(fn, sizeof fn, "%s/tok_evw.bin", dir); FILE *fe = fopen(fn, "wb");
  snprintf(fn, sizeof fn, "%s/tok_a.bin", dir); FILE *fa = fopen(fn, "wb");
  snprintf(fn, sizeof fn, "%s/tok_rec.bin", dir); FILE *fr = fopen(fn, "wb");
  snprintf(fn, sizeof fn, "%s/subsets.txt", dir); FILE *fs = fopen(fn, "w");
  int M = (int)edges.size() - 1;
  long long ntok = 0;
  size_t rec = 0;
  for (int k = 0; k < M; k++) {
    size_t r0 = rec;
    while (rec < keep.size() && keep[rec] < edges[k + 1]) rec++;
    size_t r1 = rec;
    std::fill(last.begin(), last.end(), -(1LL << 40));
    for (int L = 0; L < LANES; L++) tl[L] = 0;
    std::vector<int> pend; size_t next = r0; long nops = 0, ntk = 0;
    long long nd[LANES], bn[LANES], kv[4];
    auto emit = [&](const EvW &w, float a, int ri) { fwrite(&w, sizeof w, 1, fe); fwrite(&a, 4, 1, fa); fwrite(&ri, 4, 1, fr); ntk++; };
    while (next < r1 || !pend.empty()) {
      while (pend.size() < 64 && next < r1) pend.push_back((int)next++);
      int best = -1; long long bs = 1LL << 60;
      for (size_t i = 0; i < pend.size(); i++) {
        long long s = need(ev[pend[i]], nd);
        if (s < bs) { bs = s; best = (int)i; memcpy(bn, nd, sizeof(bn)); }
        if (s == 0) break;
      }
      const EvIn &e = ev[pend[best]];
      while (bs > 0) {
        for (int L = 0; L < LANES; L++)
          if (bn[L] > 0) {
            EvW d; memset(&d, 0, sizeof(d)); d.i0 = -1000; d.u0 = L; d.na = (short)bn[L];
            emit(d, 0.0f, -1);
            for (int Q = 0; Q < LANES; Q++) tl[Q] += 1;
            tl[L] += bn[L] - 1; nops++;
          }
        bs = need(e, bn);
      }
      for (int L = 0; L < LANES; L++) {
        int pl, cl; lane_view(e, L, pl, cl);
        for (int j = 0; j < cl; j++) {
          int p = pl + LANES * j, kk = p - e.i0;
          int nv = voxkeys(e, kk, p, kv);
          for (int q = 0; q < nv; q++) last[kv[q]] = tl[L] + j / SETS;
        }
        tl[L] += std::max(1, (cl + SETS - 1) / SETS);
      }
      EvW w; w.i0 = e.i0; w.na = e.na; w.u0 = e.u0; w.v0 = e.v0; w.du = e.du; w.dv = e.dv; w.d0 = e.d0; w.dd = e.dd; w.mw = e.mw;
      emit(w, e.a, pend[best]);
      pend.erase(pend.begin() + best);
    }
    long long tmax = 0; for (int L = 0; L < LANES; L++) tmax = std::max(tmax, tl[L]);
    fprintf(fs, "%d %lld %ld %zu %ld %lld\n", k, ntok, ntk, r1 - r0, nops, tmax);
    printf("subset %d: tokens %ld (events %zu, NOP %ld), lane items max %lld -> %.3f items/token\n", k, ntk, r1 - r0, nops, tmax,
           (double)tmax / ntk);
    fflush(stdout);
    ntok += ntk;
  }
  fclose(fe); fclose(fa); fclose(fr); fclose(fs);
  printf("total tokens %lld\n", ntok);
  return 0;
}
