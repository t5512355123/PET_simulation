// exp state: c (current token), jb (item index within the token), rem (items left after this one), id
// items per token: events -> gl (from the annotation), CLEAR -> DEPTH, own NOP -> n, other tokens -> 1.
// exp only counts; the engine computes the steps (k, u, v, d) of the item from (token, jb, this lane's pl / tl / cl).
#define EXP_BODY                                                                                             \
  {                                                                                                          \
    bool tokit = rem == 0;                                                                                   \
    Tok t;                                                                                                   \
    if (tokit) t = in.read(); else t = c;                                                                    \
    int kind = t.kind;                                                                                       \
    bool isev = kind == K_FWD || kind == K_BACK;                                                             \
    bool isclr = kind == K_CLEAR;                                                                            \
    bool isnop = kind == K_NOP && t.u0 == id;                                                                \
    int ng = isev ? (int)t.gl : (isclr ? DEPTH : (isnop ? (int)(t.na & 0x7fff) : 0));                         \
    int jbase = tokit ? 0 : jb;                                                                              \
    int remn = tokit ? (ng > 0 ? ng - 1 : 0) : rem - 1;                                                      \
    bool any = isev && jbase * SETS < t.cl;                                                                  \
    Item it;                                                                                                 \
    it.t = t;                                                                                                \
    it.jb = jbase;                                                                                           \
    it.pl = t.pl; it.tl = t.tl; it.cl = t.cl;                                                                \
    unsigned char f = 0;                                                                                     \
    if (tokit) f |= F_TOK;                                                                                   \
    if (kind == K_FWD && any) f |= F_SF;                                                                     \
    if (kind == K_BACK && any) f |= F_SB;                                                                    \
    if (kind == K_FWD && any && remn == 0) f |= F_LAST;                                                      \
    if (tokit && kind == K_FWD && !any) f |= F_EMIT0;                                                        \
    if (isclr) f |= F_CLR;                                                                                   \
    it.fl = f;                                                                                               \
    if (tokit) {                                                                                             \
      if (kind == K_SETID) id = t.u0;                                                                        \
      annot_next(it.t, t.pl, t.tl);                                                                          \
    }                                                                                                        \
    wq.write(it);                                                                                            \
    c = t;                                                                                                   \
    rem = remn;                                                                                              \
    jb = jbase + 1;                                                                                          \
  }

