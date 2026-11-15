#include "HLS/hls.h"
#include <stdio.h>
component int add3(int a, int b) { return a + b + 3; }
int main() { int r = add3(1, 2); printf("r=%d\n", r); return r == 6 ? 0 : 1; }
