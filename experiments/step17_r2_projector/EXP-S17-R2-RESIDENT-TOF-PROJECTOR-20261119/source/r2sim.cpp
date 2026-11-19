// EXP-S17 R2 architecture model (software): both main-axis copies resident, FOV-compressed, interleaved planes,
// LANES lanes x SETS bank sets, TOF kernel table. Functional result (forward F, back image) + lane cycle counts.
//   plane p (of either copy) -> lane p % LANES, t = p / LANES, set = t % SETS, slot m = t / SETS
//   memory of (lane, set): [copy][slot] regions of rows (uh) x HZ (zh), 4 parity banks (u & 1, z & 1)
//   one lane cycle processes up to SETS consecutive local steps of one event (they are in different sets)
// Usage: r2sim <dir> <lanes> <sets>  (dir: ev_hw.bin img_fov.bin fov_rows.bin [F_ref.bin back_ref.bin s_ref.bin])
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <algorithm>

#define NPL 201
#define NU 201
#define NZ 47
#define HZ ((NZ + 1) / 2)
#define FRAC 20
static const double S = (double)(1 << FRAC);
static const double TOF_W = 5 * 89 * 0.299792458 / 2, SIG = 0.5 * 550.0 * 0.299792458 / 2.354820045;
static const double HALF = 5.0 * SIG;
#define NTAB 4096

#pragma pack(push, 1)
struct EvHW { short i0, na; int u0, v0, du, dv; float d0, dd, mw, y, a, pad; };
#pragma pack(pop)

template <class T> std::vector<T> readf(const char *fn, bool must = true) {
  std::vector<T> v;
  FILE *f = fopen(fn, "rb");
  if (!f) { if (must) { printf("cannot open %s\n", fn); exit(1); } return v; }
  fseek(f, 0, SEEK_END); long n = ftell(f) / sizeof(T); fseek(f, 0, SEEK_SET);
  v.resize(n);
  if (fread(v.data(), sizeof(T), n, f) != (size_t)n) exit(1);
  fclose(f);
  return v;
}

static float tab[NTAB + 1];
static float tofw(float d) {             // table over |d| in [0, HALF], linear interpolation (hardware form)
  float a = fabsf(d);
  if (a > HALF) return 0.0f;
  float x = a * (float)(NTAB / HALF);
  int i = (int)x; float f = x - i;
  return tab[i] + f * (tab[i + 1] - tab[i]);
}

int main(int argc, char **argv) {
  const char *dir = argv[1];
  int LANES = atoi(argv[2]), SETS = atoi(argv[3]);
  char fn[1024];
  for (int i = 0; i <= NTAB; i++) {
    double d = HALF * i / NTAB;
    tab[i] = (float)(0.5 * (erf((d + TOF_W / 2) / (sqrt(2.0) * SIG)) - erf((d - TOF_W / 2) / (sqrt(2.0) * SIG))));
  }
  snprintf(fn, sizeof fn, "%s/ev_hw.bin", dir); auto ev = readf<EvHW>(fn);
  snprintf(fn, sizeof fn, "%s/img_fov.bin", dir); auto img = readf<float>(fn);       // (z, y, x)
  snprintf(fn, sizeof fn, "%s/fov_rows.bin", dir); auto rows = readf<int>(fn);       // [copy][plane][lo, hi] (u)
  int NE = (int)ev.size();
  // ---- memory layout: per (copy, plane): lane, set, slot, base row, uh_lo, number of rows
  int ulo[2][NPL], nrow[2][NPL], base[2][NPL];
  std::vector<long> depth((size_t)LANES * SETS, 0);
  for (int c = 0; c < 2; c++)
    for (int p = 0; p < NPL; p++) {
      int lo = rows[(c * NPL + p) * 2], hi = rows[(c * NPL + p) * 2 + 1];
      ulo[c][p] = lo < 0 ? 0 : lo >> 1;
      nrow[c][p] = lo < 0 ? 0 : (hi >> 1) - (lo >> 1) + 1;
    }
  for (int L = 0; L < LANES; L++)
    for (int s = 0; s < SETS; s++) {
      long acc = 0;
      for (int c = 0; c < 2; c++)
        for (int p = L; p < NPL; p += LANES) {
          int t = p / LANES;
          if (t % SETS != s) continue;
          base[c][p] = (int)acc;
          acc += (long)nrow[c][p] * HZ;
        }
      depth[L * SETS + s] = acc;
    }
  long dmax = *std::max_element(depth.begin(), depth.end()), dsum = 0;
  for (long d : depth) dsum += d;
  long words_alloc = dmax * LANES * SETS * 4;     // per array (4 parity banks)
  printf("memory: bank depth max %ld (mean %.0f) -> per array %ld words allocated (%.1f%% used); "
         "M20K: ACC fp32 %ld + IMG fp16 %ld = %ld blocks\n", dmax, (double)dsum / depth.size(), words_alloc,
         100.0 * dsum * 4 / words_alloc, (long)ceil(dmax / 512.0) * 4 * LANES * SETS, (long)ceil(dmax / 1024.0) * 4 * LANES * SETS,
         (long)ceil(dmax / 512.0) * 4 * LANES * SETS + (long)ceil(dmax / 1024.0) * 4 * LANES * SETS);
  // ---- load the image into the two copies (IMG stored as fp16 -> rounded here)
  std::vector<float> IMG(2 * (size_t)NPL * 0 + 1);
  auto mem_index = [&](int c, int p, int u, int z, long &idx) -> bool {   // flat index in a virtual [copy][plane] memory
    int uh = u >> 1;
    if (uh < ulo[c][p] || uh >= ulo[c][p] + nrow[c][p]) return false;
    idx = (((long)c * NPL + p) * (NU + 1) / 2 + uh) * HZ * 4 + (z >> 1) * 4 + ((u & 1) | ((z & 1) << 1));
    return true;
  };
  const long VM = 2L * NPL * ((NU + 1) / 2) * HZ * 4;
  std::vector<float> img16(VM, 0.0f), acc(VM, 0.0f);
  for (int z = 0; z < NZ; z++)
    for (int y = 0; y < NPL; y++)
      for (int x = 0; x < NPL; x++) {
        float v = img[((size_t)z * NPL + y) * NPL + x];
        long i;
        if (mem_index(0, x, y, z, i)) img16[i] = v;
        if (mem_index(1, y, x, z, i)) img16[i] = v;
      }
  // fp16 rounding of the stored image (round to nearest, 10-bit mantissa)
  for (auto &v : img16) { if (v != 0.0f) { int e; float m = frexpf(v, &e); m = roundf(m * 2048.0f) / 2048.0f; v = ldexpf(m, e); } }
  // ---- per event: forward F (sum over lanes), lane cycles
  std::vector<double> F(NE, 0.0);
  std::vector<long> cyc(LANES, 0), cycs(LANES, 0);
  long steps_total = 0, steps_used = 0;
  for (int e = 0; e < NE; e++) {
    const EvHW &r = ev[e];
    int c = (r.na >> 15) & 1, n = r.na & 0x7fff;
    steps_total += n;
    std::vector<int> cnt(LANES, 0);
    double Fe = 0.0;
    for (int k = 0; k < n; k++) {
      int p = r.i0 + k;
      int L = p % LANES;
      cnt[L]++;
      double u = (r.u0 + (long)k * r.du) / S, v = (r.v0 + (long)k * r.dv) / S;
      int iu = (int)floor(u), iv = (int)floor(v);
      float fu = (float)(u - iu), fv = (float)(v - iv);
      float tw = tofw(r.d0 + k * r.dd);
      for (int b = 0; b < 4; b++) {
        int cu = iu + (b & 1), cz = iv + (b >> 1);
        if (cu < 0 || cu >= NU || cz < 0 || cz >= NZ) continue;
        long i;
        if (!mem_index(c, p, cu, cz, i)) continue;
        float w = ((b & 1) ? fu : 1 - fu) * ((b >> 1) ? fv : 1 - fv);
        Fe += (double)(w * tw) * img16[i];
        steps_used++;
      }
    }
    F[e] = Fe * r.mw;
    for (int L = 0; L < LANES; L++) { cyc[L] += std::max(1, (cnt[L] + SETS - 1) / SETS); cycs[L] += (cnt[L] + SETS - 1) / SETS; }
  }
  // back projection with s = 1 / (F + a) (the hardware ratio with y = 1, divided by mw: s_hw = mw / (mw F + a))
  for (int e = 0; e < NE; e++) {
    const EvHW &r = ev[e];
    int c = (r.na >> 15) & 1, n = r.na & 0x7fff;
    float shw = (float)(r.mw / (F[e] + r.a));
    for (int k = 0; k < n; k++) {
      int p = r.i0 + k;
      double u = (r.u0 + (long)k * r.du) / S, v = (r.v0 + (long)k * r.dv) / S;
      int iu = (int)floor(u), iv = (int)floor(v);
      float fu = (float)(u - iu), fv = (float)(v - iv);
      float tw = tofw(r.d0 + k * r.dd);
      for (int b = 0; b < 4; b++) {
        int cu = iu + (b & 1), cz = iv + (b >> 1);
        if (cu < 0 || cu >= NU || cz < 0 || cz >= NZ) continue;
        long i;
        if (!mem_index(c, p, cu, cz, i)) continue;
        float w = ((b & 1) ? fu : 1 - fu) * ((b >> 1) ? fv : 1 - fv);
        acc[i] += shw * w * tw;
      }
    }
  }
  long smax = *std::max_element(cycs.begin(), cycs.end());
  printf("with token skip (forwarder, chain >= 1 event per cycle): busiest lane %ld cycles -> %ld\n", smax,
         std::max(smax, (long)NE));
  printf("M20K with one shared fp32 word per voxel (IMG during forward, ACC during back): %ld blocks\n",
         (long)ceil(dmax / 512.0) * 4 * LANES * SETS);
  long cmax = *std::max_element(cyc.begin(), cyc.end()), csum = 0;
  for (long x : cyc) csum += x;
  printf("events %d, steps %ld (%.1f/event); lane cycles per pass: max %ld, mean %.0f (balance %.3f); "
         "efficiency steps/(lanes*sets*max) %.3f\n", NE, steps_total, (double)steps_total / NE, cmax, (double)csum / LANES,
         (double)csum / LANES / cmax, (double)steps_total / LANES / SETS / cmax);
  // ---- compare with the GPU reference
  snprintf(fn, sizeof fn, "%s/F_ref.bin", dir); auto Fr = readf<double>(fn, false);
  snprintf(fn, sizeof fn, "%s/back_ref.bin", dir); auto Br = readf<float>(fn, false);
  if (!Fr.empty() && !Br.empty()) {
    std::vector<double> Fs(F);
    std::sort(Fs.begin(), Fs.end());
    double med = Fs[NE / 2], eF = 0, eFr = 0;
    for (int e = 0; e < NE; e++) { eF = fmax(eF, fabs(F[e] - Fr[e]) / med); if (Fr[e] > 1e-3 * med) eFr = fmax(eFr, fabs(F[e] - Fr[e]) / Fr[e]); }
    double bm = 0, be = 0;
    for (int z = 0; z < NZ; z++)
      for (int y = 0; y < NPL; y++)
        for (int x = 0; x < NPL; x++) {
          long i0, i1; double h = 0;
          if (mem_index(0, x, y, z, i0)) h += acc[i0];
          if (mem_index(1, y, x, z, i1)) h += acc[i1];
          // reference is the full image: compare inside the FOV only (outside the hardware does not store)
          bool in = mem_index(0, x, y, z, i0);
          double rf = Br[((size_t)z * NPL + y) * NPL + x];
          if (in) { bm = fmax(bm, fabs(rf)); be = fmax(be, fabs(h - rf)); }
        }
    printf("vs GPU parallelproj (FOV image): forward max |dF| / median F %.3e, max rel (F > 1e-3 median) %.3e; "
           "back max abs diff / max (inside FOV) %.3e\n", eF, eFr, be / bm);
  }
  return 0;
}
