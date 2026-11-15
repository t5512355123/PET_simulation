#include "HLS/hls.h"
component int f(hls_avalon_slave_memory_argument(262144*4) int *m, int i) { return m[i]; }
int main(){ static int m[262144]; m[3]=5; return f(m,3)==5?0:1; }
