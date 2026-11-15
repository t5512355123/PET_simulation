"""Force 8 independent parity banks: IMG/ACC as [BANKSZ][NB] with hls_numbanks(NB) hls_bankwidth(4)."""
import re

p = 'lanes_part.cpp'
s = open(p, encoding='utf-8').read()
n0 = len(s)
s = re.sub(r'static float IMG\[NB\]\[BANKSZ\];', 'hls_numbanks(NB) hls_bankwidth(4) hls_singlepump static float IMG[BANKSZ][NB];', s)
s = re.sub(r'static float ACC\[NB\]\[BANKSZ\];', 'hls_numbanks(NB) hls_bankwidth(4) hls_singlepump static float ACC[BANKSZ][NB];', s)
reps = [
    ('if (b == bb) IMG[b][ad] = v;', 'if (b == bb) IMG[ad][b] = v;'),
    ('if (b == bb) { sum = ACC[b][ad]; ACC[b][ad] = 0.0f; }', 'if (b == bb) { sum = ACC[ad][b]; ACC[ad][b] = 0.0f; }'),
    ('val += wt[b] * IMG[b][addr[b]];', 'val += wt[b] * IMG[addr[b]][b];'),
    ('if (ok[b]) ACC[b][addr[b]] += st.s * wt[b];', 'if (ok[b]) ACC[addr[b]][b] += st.s * wt[b];'),
]
for a, b in reps:
    assert a in s, a
    s = s.replace(a, b)
assert 'IMG[BANKSZ][NB]' in s and 'ACC[BANKSZ][NB]' in s
open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('patched lanes_part.cpp', n0, '->', len(s))
