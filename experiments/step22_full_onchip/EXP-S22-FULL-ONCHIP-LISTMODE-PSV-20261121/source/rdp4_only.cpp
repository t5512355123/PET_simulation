#include "HLS/hls.h"
#include "HLS/math.h"
#include "HLS/lsu.h"
#include <math.h>
struct D512 { float v[16]; };
struct D512U { unsigned v[16]; };
union FU { float f; unsigned u; };
static inline float bf2f(unsigned h) { FU x; x.u = h << 16; return x.f; }
static inline unsigned f2bf(float f) { FU x; x.f = f; return (x.u + 0x7fffu + ((x.u >> 16) & 1u)) >> 16; }
#define RS 208
#define PS (201 * RS)
#define RB_WORDS 51
#define ASP_XR 3
#define ASP_GP 4
#define HOSTA(T, AS) ihc::mm_master<T, ihc::aspace<AS>, ihc::awidth<34>, ihc::dwidth<512>, ihc::latency<0>, ihc::maxburst<64>, ihc::waitrequest<true>>
typedef ihc::lsu<ihc::style<ihc::PIPELINED>> PLSU;
#define LDP(m, i) PLSU::load(&(m)[i])
// RDP unit v4 (own clock domain): mode 0 gradient / 1 Hessian diagonal, slot-order output
hls_avalon_slave_component component int slab_rdp(
    hls_avalon_slave_register_argument HOSTA(D512, ASP_XR) &xin, hls_avalon_slave_register_argument HOSTA(D512U, ASP_XR) &kin,
    hls_avalon_slave_register_argument HOSTA(D512, ASP_XR) &mb, hls_avalon_slave_register_argument HOSTA(D512, ASP_GP) &mo,
    hls_avalon_slave_register_argument int mode, hls_avalon_slave_register_argument int braster,
    hls_avalon_slave_register_argument int nz, hls_avalon_slave_register_argument float eps2,
    hls_avalon_slave_register_argument float w1, hls_avalon_slave_register_argument float w2,
    hls_avalon_slave_register_argument float w3, hls_avalon_slave_register_argument float w4,
    hls_avalon_slave_register_argument float w5) {
#define MEMATTRX hls_singlepump hls_force_pow2_depth(0)
#define MEMATTRK hls_singlepump hls_force_pow2_depth(0)
#define MEMATTRC hls_singlepump hls_force_pow2_depth(0)
#include "rdp4_body.inc"
  return nz;
}
int main() { return 0; }
