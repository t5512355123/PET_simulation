int main(int argc, char **argv) {
  const char *dir = argv[1];
  int HAZ = argc > 2 ? atoi(argv[2]) : 80;
  int NMAX = argc > 3 ? atoi(argv[3]) : 1 << 30;     // events used (board batches hold MAXEV tokens)
  char fn[1024];
  snprintf(fn, sizeof fn, "%s/ev_hw.bin", dir); auto evin = readf<EvIn>(fn);
  snprintf(fn, sizeof fn, "%s/img_fov.bin", dir); auto img = readf<float>(fn);
  snprintf(fn, sizeof fn, "%s/fov_rows.bin", dir); auto rows = readf<int>(fn);
  int NE = std::min((int)evin.size(), NMAX);
  std::vector<Ev> ev(NE);
  for (int i = 0; i < NE; i++) {
    const EvIn &r = evin[i]; Ev &e = ev[i];
    e.i0 = r.i0; e.na = r.na; e.u0 = r.u0; e.v0 = r.v0; e.du = r.du; e.dv = r.dv; e.d0 = r.d0; e.dd = r.dd;
    e.mw = r.mw; e.y = r.y; e.a = r.a;
    int p0 = ((r.i0 + LANES - 1) / LANES) * LANES;
    e.p0 = (short)p0; e.t0 = (short)(p0 / LANES);
    e.c0 = local_cnt(e.p0, e.i0, e.na & 0x7fff); e.g0 = (short)((e.c0 + SETS - 1) / SETS);
  }
  // ---- plane tables
  int ulo[2][NPL], nrow[2][NPL];
  for (int c = 0; c < 2; c++)
    for (int p = 0; p < NPL; p++) {
      int lo = rows[(c * NPL + p) * 2], hi = rows[(c * NPL + p) * 2 + 1];
      ulo[c][p] = lo < 0 ? 0 : lo >> 1;
      nrow[c][p] = lo < 0 ? 0 : (hi >> 1) - (lo >> 1) + 1;
    }
  static int base[LANES][2][TMAX];
  long dmax = 0;
  for (int L = 0; L < LANES; L++)
    for (int s = 0; s < SETS; s++) {
      long acc = 0;
      for (int c = 0; c < 2; c++)
        for (int t = s; t < TMAX; t += SETS) {
          int p = L + LANES * t;
          if (p >= NPL) continue;
          base[L][c][t] = (int)acc;
          acc += (long)nrow[c][p] * HZ;
        }
      dmax = std::max(dmax, acc);
    }
  printf("lanes %d sets %d: bank depth needed %ld (DEPTH %d)\n", LANES, SETS, dmax, DEPTH);
  if (dmax > DEPTH) { printf("DEPTH too small\n"); return 1; }
  auto inrow = [&](int c, int p, int u) { return nrow[c][p] > 0 && (u >> 1) >= ulo[c][p] && (u >> 1) < ulo[c][p] + nrow[c][p]; };
  // ---- hazard-free order (back projection read-modify-write): lane time model = items of the exp
  auto lane_view = [&](const Ev &e, int L, int &pl, int &cl) {
    int n = e.na & 0x7fff;
    int r = ((L - e.i0) % LANES + LANES) % LANES;
    pl = e.i0 + r;
    cl = local_cnt((short)pl, e.i0, (short)n);
  };
  std::vector<long long> last((size_t)2 * NPL * (NU + 1) * (NZ + 1), -(1LL << 40));
  long long tl[LANES];
  for (int L = 0; L < LANES; L++) tl[L] = 0;
  auto voxkeys = [&](const Ev &e, int k, int p, long long *keys) {
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
  auto need = [&](const Ev &e, long long nd[LANES]) {
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
  std::vector<Ev> sch; std::vector<int> gidx;
  std::vector<int> pend; size_t next = 0; long nops = 0, bub = 0;
  long long nd[LANES], bn[LANES], kv[4];
  while (next < (size_t)NE || !pend.empty()) {
    while (pend.size() < 64 && next < (size_t)NE) pend.push_back((int)next++);
    int best = -1; long long bs = 1LL << 60;
    for (size_t i = 0; i < pend.size(); i++) {
      long long s = need(ev[pend[i]], nd);
      if (s < bs) { bs = s; best = (int)i; memcpy(bn, nd, sizeof(bn)); }
      if (s == 0) break;
    }
    const Ev &e = ev[pend[best]];
    while (bs > 0) {
      for (int L = 0; L < LANES; L++)
        if (bn[L] > 0) {
          Ev d; memset(&d, 0, sizeof(d)); d.i0 = -1000; d.u0 = L; d.na = (short)bn[L];
          sch.push_back(d); gidx.push_back(-1);
          for (int M = 0; M < LANES; M++) tl[M] += 1;
          tl[L] += bn[L] - 1; nops++; bub += bn[L];
        }
      bs = need(e, bn);
    }
    for (int L = 0; L < LANES; L++) {
      int pl, cl; lane_view(e, L, pl, cl);
      for (int j = 0; j < cl; j++) {
        int p = pl + LANES * j, k = p - e.i0;
        int nv = voxkeys(e, k, p, kv);
        for (int q = 0; q < nv; q++) last[kv[q]] = tl[L] + j / SETS;
      }
      tl[L] += std::max(1, (cl + SETS - 1) / SETS);
    }
    sch.push_back(e); gidx.push_back(pend[best]);
    pend.erase(pend.begin() + best);
  }
  long long tmax = 0, tsum = 0;
  for (int L = 0; L < LANES; L++) { tmax = std::max(tmax, tl[L]); tsum += tl[L]; }
  int NS = (int)sch.size();
  printf("scheduled %d tokens (%d events, %ld NOP, %ld bubbles); lane items max %lld mean %.0f\n", NS, NE, nops, bub, tmax,
         (double)tsum / LANES);
  if (NS > MAXEV) printf("WARNING: %d tokens > MAXEV %d (board batch)\n", NS, MAXEV);
  // ---- board files: raw setup tokens, row table + sweep, chunk starts
  std::vector<Tok> raw;
  raw.push_back(ctok(K_SETID, 0, 0, 0, 0, 0, 0, 0, 0));
  for (int L = 0; L < LANES; L++)
    for (int c = 0; c < 2; c++)
      for (int t = 0; t < TMAX; t++) {
        int p = L + LANES * t;
        int b = (p < NPL) ? base[L][c][t] : 0, u = (p < NPL) ? ulo[c][p] : 0, nr = (p < NPL) ? nrow[c][p] : 0;
        raw.push_back(ctok(K_SETUP, L, c, t, b, (float)u, (float)nr, 0, 0));
      }
  const double W = 5 * 89 * 0.299792458 / 2, SIG = 0.5 * 550.0 * 0.299792458 / 2.354820045;
  auto kern = [&](double d) { return 0.5 * (erf((d + W / 2) / (sqrt(2.0) * SIG)) - erf((d - W / 2) / (sqrt(2.0) * SIG))); };
  for (int i = 0; i < TOFN; i++)
    raw.push_back(ctok(K_TOFTAB, i, 0, 0, 0, (float)kern(TOFHALF * i / TOFN), (float)kern(TOFHALF * (i + 1) / TOFN), 0, 0));
  snprintf(fn, sizeof fn, "%s/hw7/raw_setup.bin", dir); writef(fn, raw);
  std::vector<Tok> rclr(1, ctok(K_CLEAR, 0, 0, 0, 0, 0, 0, 0, 0));
  snprintf(fn, sizeof fn, "%s/hw7/raw_clear.bin", dir); writef(fn, rclr);
  struct RowE { short copy, plane, lane, t; short ulo2, nrow; int pad; };
  std::vector<RowE> rt;
  std::vector<float> sweepv; std::vector<int> sweeppos;
  for (int c = 0; c < 2; c++)
    for (int p = 0; p < NPL; p++) {
      if (nrow[c][p] == 0) continue;
      RowE r; r.copy = (short)c; r.plane = (short)p; r.lane = (short)(p % LANES); r.t = (short)(p / LANES);
      r.ulo2 = (short)ulo[c][p]; r.nrow = (short)nrow[c][p]; r.pad = std::min(2 * (ulo[c][p] + nrow[c][p]), NU);
      rt.push_back(r);
      for (int u = 2 * ulo[c][p]; u < r.pad; u++)
        for (int z = 0; z < NZ; z++) {
          int x = c ? u : p, y = c ? p : u;
          sweepv.push_back(img[((size_t)z * NPL + y) * NPL + x]);
          sweeppos.push_back((int)(((size_t)z * NPL + y) * NPL + x));
        }
    }
  RowE pad_; memset(&pad_, 0, sizeof(pad_)); rt.push_back(pad_);   // src reads one entry past the end
  snprintf(fn, sizeof fn, "%s/hw7/rowt.bin", dir); writef(fn, rt);
  snprintf(fn, sizeof fn, "%s/hw7/img_sweep.bin", dir); writef(fn, sweepv);
  {   // chunk starts (row entry, u, z) for chunks of IOCHUNK voxels
    snprintf(fn, sizeof fn, "%s/hw7/chunks.txt", dir); FILE *f = fopen(fn, "w");
    long i = 0; int r = 0, u = 2 * rt[0].ulo2, z = 0;
    while (i < (long)sweepv.size()) {
      long cnt = std::min((long)IOCHUNK, (long)sweepv.size() - i);
      fprintf(f, "%ld %d %d %d %ld\n", i, r, u, z, cnt);
      for (long q = 0; q < cnt; q++) {   // advance like the src sweep
        bool zw = z == NZ - 1, uw = u == rt[r].pad - 1;
        z = zw ? 0 : z + 1; u = zw ? (uw ? 0 : u + 1) : u;
        if (zw && uw) { r++; u = 2 * rt[r].ulo2; }
      }
      i += cnt;
    }
    fclose(f);
  }
  snprintf(fn, sizeof fn, "%s/hw7/ev7.bin", dir); writef(fn, sch);
  // ---- run the model on the scheduled tokens: setup, load (sweep), forward, clear, back, read (sweep)
  for (int L = 0; L < LANES; L++) { LM[L] = (LaneMem *)calloc(1, sizeof(LaneMem)); LM[L]->rst = true; LM[L]->c.kind = K_NOP; }
  SQ<Tok> t0, tN; SQ<PTok> p0, pN;
  for (auto &r : raw) t0.write(r);
  chain(t0, p0, tN, pN, NULL);
  {
    size_t i = 0;
    for (size_t r = 0; r + 1 < rt.size(); r++)
      for (int u = 2 * rt[r].ulo2; u < rt[r].pad; u++)
        for (int z = 0; z < NZ; z++)
          t0.write(ctok(K_LOAD, u, z, rt[r].lane, rt[r].t, 0, 0, sweepv[i++], rt[r].copy));
  }
  chain(t0, p0, tN, pN, NULL);
  long items[LANES];
  int nf = 0;
  for (int i = 0; i < NS; i++) { t0.write(ev2tok(sch[i], 0, 0.0f)); if (sch[i].i0 != -1000) { p0.write(ev2ptok(sch[i], i, 0.0f)); nf++; } }
  chain(t0, p0, tN, pN, items);
  std::vector<float> s(NS, 0.0f), Fhw(NE, 0.0f);
  while (!pN.empty()) { PTok r = pN.read(); s[r.idx] = ratio(r); if (gidx[r.idx] >= 0) Fhw[gidx[r.idx]] = r.F * r.mw; }
  long imax = *std::max_element(items, items + LANES);
  printf("forward (model): lane items max %ld (scheduler %lld)\n", imax, tmax);
  t0.write(ctok(K_CLEAR, 0, 0, 0, 0, 0, 0, 0, 0));
  chain(t0, p0, tN, pN, NULL);
  for (int i = 0; i < NS; i++) t0.write(ev2tok(sch[i], 1, s[i]));
  chain(t0, p0, tN, pN, NULL);
  {
    for (size_t r = 0; r + 1 < rt.size(); r++)
      for (int u = 2 * rt[r].ulo2; u < rt[r].pad; u++)
        for (int z = 0; z < NZ; z++) t0.write(ctok(K_READ, u, z, rt[r].lane, rt[r].t, 0, 0, 0, rt[r].copy));
  }
  chain(t0, p0, tN, pN, NULL);
  std::vector<float> rd(sweepv.size()), back((size_t)NZ * NPL * NPL, 0.0f);
  for (size_t i = 0; i < rd.size(); i++) { rd[i] = tN.read().s; back[sweeppos[i]] += rd[i]; }
  snprintf(fn, sizeof fn, "%s/hw7/expect_s.bin", dir); writef(fn, s);
  snprintf(fn, sizeof fn, "%s/hw7/expect_read.bin", dir); writef(fn, rd);
  snprintf(fn, sizeof fn, "%s/hw7/sweep_pos.bin", dir); writef(fn, sweeppos);
  snprintf(fn, sizeof fn, "%s/hw7/meta.txt", dir); FILE *mf = fopen(fn, "w");
  fprintf(mf, "nev %d\nnf %d\nnsweep %zu\nnrowt %zu\nnraw %zu\nhaz %d\nmax_lane_items %lld\nevents %d\nnops %ld\n", NS, nf,
          sweepv.size(), rt.size() - 1, raw.size(), HAZ, tmax, NE, nops);
  fclose(mf);
  // ---- compare with the GPU reference (events in input order, first NE)
  snprintf(fn, sizeof fn, "%s/F_ref.bin", dir); auto Fr = readf<double>(fn, false);
  snprintf(fn, sizeof fn, "%s/back_ref.bin", dir); auto Br = readf<float>(fn, false);
  if (!Fr.empty() && NE == (int)evin.size()) {
    std::vector<double> Fs(Fr.begin(), Fr.begin() + NE); std::sort(Fs.begin(), Fs.end()); double med = Fs[NE / 2], eF = 0;
    for (int i = 0; i < NE; i++) eF = std::max(eF, fabs(Fhw[i] - Fr[i]) / med);
    double bm = 0, be = 0;
    for (size_t i = 0; i < sweeppos.size(); i++) { int q = sweeppos[i]; bm = std::max(bm, (double)fabs(Br[q])); be = std::max(be, (double)fabs(back[q] - Br[q])); }
    printf("vs GPU parallelproj: forward max |dF| / median F %.3e; back (FOV) max abs diff / max %.3e\n", eF, be / bm);
  }
  return 0;
}
