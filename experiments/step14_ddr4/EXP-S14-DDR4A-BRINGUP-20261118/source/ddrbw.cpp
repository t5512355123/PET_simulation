// EXP-S14 DDR4 bring-up: write / check / stream DDR4 through a 512-bit Avalon-MM host (burst coalesced).
// mode 0: write pattern to words [0, n); mode 1: read back and count mismatches; mode 2: read only (bandwidth),
// mode 3: write only (bandwidth). Returns the mismatch count (mode 1) or a checksum.
#include "HLS/hls.h"
#include <stdio.h>

struct W { unsigned int v[16]; };   // 64 B = one 512-bit word

static inline unsigned int pat(unsigned int seed, unsigned int i, int j) {
  unsigned int x = seed ^ (i * 2654435761u) ^ ((unsigned int)j * 40503u);
  x ^= x >> 13; x *= 0x5bd1e995u; x ^= x >> 15;
  return x;
}

hls_avalon_slave_component component unsigned int ddrbw(
    hls_avalon_slave_register_argument ihc::mm_master<W, ihc::aspace<1>, ihc::awidth<34>, ihc::dwidth<512>,
                                                      ihc::latency<0>, ihc::maxburst<64>, ihc::waitrequest<true>> &m,
    hls_avalon_slave_register_argument int mode, hls_avalon_slave_register_argument int n,
    hls_avalon_slave_register_argument unsigned int seed) {
  unsigned int acc = 0;
  if (mode == 0 || mode == 3) {
    for (int i = 0; i < n; i++) {
      W w;
#pragma unroll
      for (int j = 0; j < 16; j++) w.v[j] = (mode == 0) ? pat(seed, i, j) : (unsigned int)(i + j);
      m[i] = w;
    }
    return 0;
  }
  for (int i = 0; i < n; i++) {
    W w = m[i];
    unsigned int e = 0;
#pragma unroll
    for (int j = 0; j < 16; j++) e += (mode == 1) ? (w.v[j] != pat(seed, i, j)) : w.v[j];
    acc += e;
  }
  return acc;
}

int main() {
  static W mem[1024];
  ihc::mm_master<W, ihc::aspace<1>, ihc::awidth<34>, ihc::dwidth<512>, ihc::latency<0>, ihc::maxburst<64>,
                 ihc::waitrequest<true>> mm(mem, sizeof(mem));
  ddrbw(mm, 0, 1024, 7);
  unsigned int err = ddrbw(mm, 1, 1024, 7);
  mem[5].v[3] ^= 1;
  unsigned int err2 = ddrbw(mm, 1, 1024, 7);
  printf("errors %u (expect 0), after flip %u (expect 1)\n", err, err2);
  return (err == 0 && err2 == 1) ? 0 : 1;
}
