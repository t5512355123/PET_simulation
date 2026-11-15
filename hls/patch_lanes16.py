"""Extend lanes_part.cpp to 8 and 16 lanes."""
p = 'lanes_part.cpp'
s = open(p, encoding='utf-8').read()
old_def = """DEFINE_LANE(0)
#if LANES > 1
DEFINE_LANE(1)
#endif
#if LANES > 2
DEFINE_LANE(2)
DEFINE_LANE(3)
#endif
"""
new_def = """DEFINE_LANE(0)
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
"""
assert old_def in s
s = s.replace(old_def, new_def)
old_for = "#define FOR_LANES(X) X(0) IF1(X(1)) IF2(X(2) X(3))"
assert old_for in s
s = s.replace(old_for, """#if LANES > 4
#define IF4(x) x
#else
#define IF4(x)
#endif
#if LANES > 8
#define IF8(x) x
#else
#define IF8(x)
#endif
#define FOR_LANES(X) X(0) IF1(X(1)) IF2(X(2) X(3)) IF4(X(4) X(5) X(6) X(7)) IF8(X(8) X(9) X(10) X(11) X(12) X(13) X(14) X(15))""")
open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('lanes up to 16')
