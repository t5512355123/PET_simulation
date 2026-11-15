"""Build an N-lane kernel from ev_v5.cpp + lanes_part.cpp. Usage: python make_v6.py <out.cpp>"""
import sys
OUTF = sys.argv[1]
s = open('ev_v5.cpp', encoding='utf-8').read()
lanes = open('lanes_part.cpp', encoding='utf-8').read()
a = s.index('ihc::stream<StepF, ihc::buffer<256>> sf;')
b = s.index('static inline void step_geom(')
c = s.index('// compute engine: owns the on-chip image and accumulator')
d = s.index('#ifndef NO_TESTBENCH')
s = s[:a] + lanes.replace('// GEOM_PLACEHOLDER', s[b:c]) + s[d:]

i0 = s.index('  long long bubbles;\n  std::vector<Ev> sch = schedule(raw, bubbles);')
i1 = s.index('  for (int off = 0; off < NB * BANKSZ; off += IOCHUNK) {')
s = s[:i0] + r'''  long long bubbles = 0;
  std::vector<std::vector<Ev>> per(LANES), sl(LANES);
  int ACT = getenv(\"ACTIVE\") ? atoi(getenv(\"ACTIVE\")) : LANES;
  for (size_t i = 0; i < raw.size(); i++) per[i % ACT].push_back(raw[i]);
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
''' + s[i1:]
s = s.replace("  ev_lane(ev, s_out, io, 1, ne, 0, (int)steps, 1);",
              "  for (int L = 0; L < LANES; L++) io[L] = (float)lane_steps[L];\n  ev_lane(ev, s_out, io, 1, ne, 0, 0, 1);")
old_meta = 'f = fopen("meta.txt", "w"); fprintf(f, "nev %d\\nsteps %lld\\nvoxels %d\\nreal_steps %lld\\n", ne, steps, NB * BANKSZ, real_steps); fclose(f);'
assert old_meta in s
s = s.replace(old_meta, 'f = fopen("meta.txt", "w"); fprintf(f, "nev %d\\nsteps %lld\\nvoxels %d\\nreal_steps %lld\\nlanes %d\\nmaxlane %lld\\n", ne, steps, NB * BANKSZ, real_steps, LANES, maxlane); fclose(f);\n'
              '    { float ls[LANES]; for (int L = 0; L < LANES; L++) ls[L] = (float)lane_steps[L]; f = fopen("lane_steps.bin", "wb"); fwrite(ls, sizeof(float), LANES, f); fclose(f); }')
open(OUTF, 'w', encoding='utf-8', newline='\n').write(s)
print(OUTF, 'written')
