#ifndef LANES
#define LANES 4
#endif
struct EvB { Ev e; float s; };

// GEOM_PLACEHOLDER

#define DEFINE_LANE(L)                                                                                     \
  ihc::stream<Ev, ihc::buffer<64>> evq##L;                                                                 \
  ihc::stream<EvB, ihc::buffer<64>> evb##L;                                                                \
  ihc::stream<StepF, ihc::buffer<256>> sf##L;                                                              \
  ihc::stream<EvP, ihc::buffer<64>> se##L;                                                                 \
  ihc::stream<float, ihc::buffer<MAXEV>> ss##L;                                                            \
  ihc::stream<StepB, ihc::buffer<256>> sb##L;                                                              \
  ihc::stream<float, ihc::buffer<256>> lin##L;                                                             \
  ihc::stream<float, ihc::buffer<256>> lout##L;                                                            \
  void prod_f##L(int nev, int total) {                                                                     \
    Ev c = evq##L.read();                                                                                  \
    { EvP q; q.mw = c.mw; q.y = c.y; q.a = c.a; se##L.write(q); }                                          \
    int k = 0;                                                                                             \
    for (int t = 0; t < total; t++) {                                                                      \
      int n = c.n_axis & 0x7fff;                                                                           \
      StepF st; st.u = c.u0 + k * c.du; st.v = c.v0 + k * c.dv; st.p = (short)(c.i0 + k);                  \
      st.axis = (unsigned char)((c.n_axis >> 15) & 1); st.last = (k == n - 1);                             \
      sf##L.write(st);                                                                                     \
      if (st.last) {                                                                                       \
        if (t < total - 1) { c = evq##L.read(); EvP q; q.mw = c.mw; q.y = c.y; q.a = c.a; se##L.write(q); } \
        k = 0;                                                                                             \
      } else {                                                                                             \
        k++;                                                                                               \
      }                                                                                                    \
    }                                                                                                      \
  }                                                                                                        \
  void prod_b##L(int nev, int total) {                                                                     \
    EvB cb = evb##L.read();                                                                                \
    int k = 0;                                                                                             \
    for (int t = 0; t < total; t++) {                                                                      \
      int n = cb.e.n_axis & 0x7fff;                                                                        \
      StepB st; st.u = cb.e.u0 + k * cb.e.du; st.v = cb.e.v0 + k * cb.e.dv; st.p = (short)(cb.e.i0 + k);   \
      st.axis = (unsigned char)((cb.e.n_axis >> 15) & 1); st.pad = 0; st.s = cb.s;                         \
      sb##L.write(st);                                                                                     \
      if (k == n - 1) {                                                                                    \
        if (t < total - 1) cb = evb##L.read();                                                             \
        k = 0;                                                                                             \
      } else {                                                                                             \
        k++;                                                                                               \
      }                                                                                                    \
    }                                                                                                      \
  }                                                                                                        \
  void eng##L(int mode, int total, int off) {                                                              \
    hls_numbanks(NB) hls_bankwidth(4) hls_singlepump static float IMG[BANKSZ][NB];                                                                          \
    hls_numbanks(NB) hls_bankwidth(4) hls_singlepump static float ACC[BANKSZ][NB];                                                                          \
    if (mode == 0) {                                                                                       \
      _Pragma("ivdep array(IMG)")                                                                          \
      for (int i = 0; i < total; i++) {                                                                    \
        int fi = off + i, ad = fi >> 3, bb = fi & 7;                                                       \
        float v = lin##L.read();                                                                           \
        _Pragma("unroll") for (int b = 0; b < NB; b++) if (b == bb) IMG[ad][b] = v;                        \
      }                                                                                                    \
    } else if (mode == 2) {                                                                                \
      _Pragma("ivdep array(ACC)")                                                                          \
      for (int i = 0; i < total; i++) {                                                                    \
        int fi = off + i, ad = fi >> 3, bb = fi & 7;                                                       \
        float sum = 0.0f;                                                                                  \
        _Pragma("unroll") for (int b = 0; b < NB; b++) if (b == bb) { sum = ACC[ad][b]; ACC[ad][b] = 0.0f; } \
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
        _Pragma("unroll") for (int b = 0; b < NB; b++) val += wt[b] * IMG[addr[b]][b];                     \
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
        _Pragma("unroll") for (int b = 0; b < NB; b++) if (ok[b]) ACC[addr[b]][b] += st.s * wt[b];         \
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
#if LANES > 4
DEFINE_LANE(4)
DEFINE_LANE(5)
DEFINE_LANE(6)
DEFINE_LANE(7)
#endif
#if LANES > 8
DEFINE_LANE(8)
DEFINE_LANE(9)
DEFINE_LANE(10)
DEFINE_LANE(11)
DEFINE_LANE(12)
DEFINE_LANE(13)
DEFINE_LANE(14)
DEFINE_LANE(15)
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
#if LANES > 4
#define IF4(x) x
#else
#define IF4(x)
#endif
#if LANES > 8
#define IF8(x) x
#else
#define IF8(x)
#endif
#define FOR_LANES(X) X(0) IF1(X(1)) IF2(X(2) X(3)) IF4(X(4) X(5) X(6) X(7)) IF8(X(8) X(9) X(10) X(11) X(12) X(13) X(14) X(15))

#define L0(L) ihc::launch<eng##L>(0, cnt, off);
#define W0(L) lin##L.write(v);
#define C0(L) ihc::collect<eng##L>();
#define L2(L) ihc::launch<eng##L>(2, cnt, off);
#define R2(L) sum += lout##L.read();
#define L1(L) ihc::launch<eng##L>(1, tot[L], 0); ihc::launch<prod_f##L>(nl[L], tot[L]);
#define F1(LL) if (L == LL) evq##LL.write(c);
#define C1(L) ihc::collect<prod_f##L>(); ihc::collect<eng##L>();
#define S1(LL) if (L == LL) s = ss##LL.read();
#define L3(L) ihc::launch<eng##L>(3, tot[L], 0); ihc::launch<prod_b##L>(nl[L], tot[L]);
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

