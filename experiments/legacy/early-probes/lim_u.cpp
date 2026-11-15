#include "HLS/hls.h"
component int g(int i, int v) { static int m[4194304]; m[i] = v; return m[(i+1)%4194304]; }
int main(){ return g(3,5)==0?0:1; }
