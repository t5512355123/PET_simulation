#ifndef SWSIM
// ================================================================= hardware components
hls_always_run_component component void slab_exp(ihc::stream_in<Tok, ihc::buffer<TOKBUF>> &in, ihc::stream_out<Item> &wq) {
  Tok c;
  c.i0 = 0; c.na = 0; c.u0 = 0; c.v0 = 0; c.du = 0; c.dv = 0; c.d0 = 0.0f; c.dd = 0.0f; c.s = 0.0f; c.kind = K_NOP; c.pl = 0; c.tl = 0;
  int jb = 0, id = 0;
  bool more = false;
  while (1) EXP_BODY
}

hls_always_run_component component void slab_eng(ihc::stream_in<Item, ihc::buffer<64>> &wq, ihc::stream_out<Tok> &out,
                                                  ihc::stream_out<float> &fl) {
  hls_numbanks(SETS * 4) hls_bankwidth(4) hls_singlepump static float MEM[DEPTH][SETS * 4];
  hls_numbanks(SETS) hls_bankwidth(4) hls_singlepump static float TT0[TOFN][SETS];
  hls_numbanks(SETS) hls_bankwidth(4) hls_singlepump static float TT1[TOFN][SETS];
  hls_register int TB_BASE[2][TMAX], TB_ULO[2][TMAX], TB_NROW[2][TMAX];
#pragma unroll
  for (int c = 0; c < 2; c++)
#pragma unroll
    for (int t = 0; t < TMAX; t++) { TB_BASE[c][t] = 0; TB_ULO[c][t] = 0; TB_NROW[c][t] = 0; }
  float F = 0.0f;
  bool rst = true;
  int myid = 0;
#pragma ivdep
  while (1) ENG_BODY
}

hls_always_run_component component void padd(ihc::stream_in<PTok, ihc::buffer<TOKBUF>> &pin,
                                              ihc::stream_in<float, ihc::buffer<1024>> &fl, ihc::stream_out<PTok> &pout) {
  PTok p = pin.read();
  float f = fl.read();
  p.F += f;
  pout.write(p);
}

#define NROWTAB (2 * NPL)
struct RowEnt { short copy, plane, lane, t; short ulo2, nrow; int pad; };   // u from 2*ulo2 .. 2*(ulo2+nrow)-1
// mode 7: raw tokens raw[0..cnt); mode 0: LOAD voxels from io (values in sweep order, chunk off..off+cnt of the sweep);
// mode 3: READ voxels (same sweep); mode 5: rep x forward (PTok start = finit ? s_in : 0); mode 6: rep x back (s_in)
// sweep order: rows table entries, u, z (all FOV voxels of both copies)
hls_avalon_slave_component component void slab_src(
    hls_avalon_slave_memory_argument(MAXEV * sizeof(Ev)) Ev *ev,
    hls_avalon_slave_memory_argument(MAXEV * sizeof(float)) float *s_in,
    hls_avalon_slave_memory_argument(IOCHUNK * sizeof(float)) float *io,
    hls_avalon_slave_memory_argument(RAWMAX * sizeof(Tok)) Tok *raw,
    hls_avalon_slave_memory_argument(NROWTAB * sizeof(RowEnt)) RowEnt *rowt,
    ihc::stream_out<Tok> &tout, ihc::stream_out<PTok> &pout,
    hls_avalon_slave_register_argument int mode, hls_avalon_slave_register_argument int nev,
    hls_avalon_slave_register_argument int off, hls_avalon_slave_register_argument int cnt,
    hls_avalon_slave_register_argument int rep, hls_avalon_slave_register_argument int finit,
    hls_avalon_slave_register_argument int rstart, hls_avalon_slave_register_argument int ustart,
    hls_avalon_slave_register_argument int zstart) {
  if (mode == 7) {
    for (int i = 0; i < cnt; i++) tout.write(raw[i]);
    return;
  }
  if (mode == 0 || mode == 3) {
    // sweep position (row entry r, u, z) given by the host for the start of this chunk
    int r = rstart, u = ustart, z = zstart;
    RowEnt e = rowt[r];
    for (int i = 0; i < cnt; i++) {
      float v = io[i];
      Tok t;
      t.i0 = 0; t.na = (short)(e.copy << 15); t.u0 = u; t.v0 = z; t.du = e.lane; t.dv = e.t; t.d0 = 0.0f; t.dd = 0.0f;
      t.s = mode == 0 ? v : 0.0f; t.kind = mode == 0 ? K_LOAD : K_READ; t.pl = 0; t.tl = 0;
      tout.write(t);
      bool zw = z == NZ - 1;
      bool uw = u == 2 * (e.ulo2 + e.nrow) - 1;
      z = zw ? 0 : z + 1;
      u = zw ? (uw ? 0 : u + 1) : u;
      if (zw && uw) { r = r + 1; e = rowt[r]; u = 2 * e.ulo2; }
    }
    return;
  }
  int ph = (mode == 6) ? 1 : 0;
  for (int rr = 0; rr < rep; rr++) {
    for (int i = 0; i < nev; i++) {
      Ev e = ev[i];
      float s = s_in[i];
      tout.write(ev2tok(e, ph, s));
      if (ph == 0 && e.i0 != -1000) pout.write(ev2ptok(e, i, finit ? s : 0.0f));
    }
  }
}

hls_avalon_slave_component component void slab_sink(
    hls_avalon_slave_memory_argument(MAXEV * sizeof(float)) float *s_out,
    hls_avalon_slave_memory_argument(IOCHUNK * sizeof(float)) float *io,
    ihc::stream_in<Tok> &tin, ihc::stream_in<PTok> &pin,
    hls_avalon_slave_register_argument int nm, hls_avalon_slave_register_argument int nq,
    hls_avalon_slave_register_argument int raw) {
  int mi = 0, qi = 0;
#pragma ivdep
  while (mi < nm || qi < nq) {
    if (mi < nm) {
      bool ok = false;
      Tok r = tin.tryRead(ok);
      if (ok) { io[mi & (IOCHUNK - 1)] = r.s; mi++; }
    }
    if (qi < nq) {
      bool ok = false;
      PTok p = pin.tryRead(ok);
      if (ok) { s_out[p.idx & (MAXEV - 1)] = raw ? p.F : ratio(p); qi++; }
    }
  }
}

int main() { return 0; }
#endif
