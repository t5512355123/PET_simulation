# System Console: Esser2 real-size slab run (4 passes) + timing.
# Usage: system-console --script=board4.tcl <hw dir> <rep>
set hw  [lindex $argv 0]
set REP [lindex $argv 1]
set SRC 0x00000000; set SIN 0x00020000; set SIO 0x00040000; set SEV 0x00100000
set SNK 0x00010000; set KOUT 0x00060000; set KIO 0x00080000
set C_START 0x08; set C_STATUS 0x18; set DONE 0x2
set S_MODE 0x20; set S_NEV 0x28; set S_OFF 0x30; set S_CNT 0x38; set S_REP 0x40; set S_FINIT 0x48
set K_NM 0x20; set K_NQ 0x28; set K_RAW 0x30
set NVOX [expr {82 * 163 * 95}]
set CHUNK 16384
set m [lindex [get_service_paths master] 0]
open_service master $m
puts "master: $m"
proc rd32 {a} { global m; return [master_read_32 $m $a 1] }
proc wr32 {a v} { global m; master_write_32 $m $a $v }
proc go {mode nev off cnt rep finit nm nq raw} {
  global SRC SNK C_START C_STATUS DONE S_MODE S_NEV S_OFF S_CNT S_REP S_FINIT K_NM K_NQ K_RAW
  wr32 [expr {$SNK + $K_NM}] $nm
  wr32 [expr {$SNK + $K_NQ}] $nq
  wr32 [expr {$SNK + $K_RAW}] $raw
  wr32 [expr {$SNK + $C_START}] 1
  wr32 [expr {$SRC + $S_MODE}] $mode
  wr32 [expr {$SRC + $S_NEV}] $nev
  wr32 [expr {$SRC + $S_OFF}] $off
  wr32 [expr {$SRC + $S_CNT}] $cnt
  wr32 [expr {$SRC + $S_REP}] $rep
  wr32 [expr {$SRC + $S_FINIT}] $finit
  set t0 [clock milliseconds]
  wr32 [expr {$SRC + $C_START}] 1
  while {1} {
    set st [rd32 [expr {$SNK + $C_STATUS}]]
    if {($st & $DONE) != 0} break
    if {[clock milliseconds] - $t0 > 600000} { puts "TIMEOUT mode=$mode sink=$st"; exit 1 }
  }
  set ms [expr {[clock milliseconds] - $t0}]
  while {([rd32 [expr {$SRC + $C_STATUS}]] & $DONE) == 0} {}
  wr32 [expr {$SNK + $C_STATUS}] $DONE
  wr32 [expr {$SRC + $C_STATUS}] $DONE
  return $ms
}
proc ntok {f} { return [expr {[file size $f] / 32}] }
proc load_img {p} {
  global hw NVOX CHUNK m SIO
  set fi [open [file join $hw img_p$p.bin] rb]; fconfigure $fi -translation binary
  for {set off 0} {$off < $NVOX} {incr off $CHUNK} {
    set cnt [expr {min($CHUNK, $NVOX - $off)}]
    set f [open [file join $hw chunk.bin] wb]; fconfigure $f -translation binary
    puts -nonewline $f [read $fi [expr {4 * $cnt}]]; close $f
    master_write_from_file $m [file join $hw chunk.bin] $SIO
    go 0 0 $off $cnt 1 0 $cnt 0 0
  }
  close $fi
}
proc read_acc {p} {
  global hw NVOX CHUNK m KIO
  set fo [open [file join $hw board_acc_p$p.bin] wb]; fconfigure $fo -translation binary
  for {set off 0} {$off < $NVOX} {incr off $CHUNK} {
    set cnt [expr {min($CHUNK, $NVOX - $off)}]
    go 3 0 $off $cnt 1 0 $cnt 0 0
    master_read_to_file $m [file join $hw chunk.bin] $KIO [expr {4 * $cnt}]
    set f [open [file join $hw chunk.bin] rb]; fconfigure $f -translation binary
    puts -nonewline $fo [read $f]; close $f
  }
  close $fo
}
proc glue {args} { global hw; set r [exec python3 [file join $hw .. .. glue4.py] {*}$args]; return $r }

puts "setid [go 4 0 0 0 1 0 1 0 0] ms"
set t0 [clock milliseconds]
foreach ax {0 1} {
  set p0 [expr {2 * $ax}]; set p1 [expr {2 * $ax + 1}]
  # forward, first half: raw partial sums
  load_img $p0
  set n [ntok [file join $hw fwd_p$p0.bin]]
  master_write_from_file $m [file join $hw fwd_p$p0.bin] $SEV
  puts "pass $p0 forward (raw) [go 5 $n 0 0 1 0 $n $n 1] ms"
  master_read_to_file $m [file join $hw board_fwd_p$p0.bin] $KOUT [expr {4 * $n}]
  glue finit $hw $p0 $p1
  # forward, second half: start from the first-half sums, ratio
  load_img $p1
  set n [ntok [file join $hw fwd_p$p1.bin]]
  master_write_from_file $m [file join $hw fwd_p$p1.bin] $SEV
  master_write_from_file $m [file join $hw finit_p$p1.bin] $SIN
  puts "pass $p1 forward (ratio) [go 5 $n 0 0 1 1 $n $n 0] ms"
  master_read_to_file $m [file join $hw board_fwd_p$p1.bin] $KOUT [expr {4 * $n}]
  glue sback $hw $p1 $p0
  # back projection, both halves (the accumulator does not need the image)
  foreach p [list $p1 $p0] {
    set n [ntok [file join $hw back_p$p.bin]]
    master_write_from_file $m [file join $hw back_p$p.bin] $SEV
    master_write_from_file $m [file join $hw s_back_p$p.bin] $SIN
    puts "pass $p back [go 6 $n 0 0 1 0 $n 0 0] ms"
    read_acc $p
  }
}
puts "full run (with JTAG image load and readout) [expr {[clock milliseconds] - $t0}] ms"
# timing: each pass list, forward and back, rep 1 and rep REP (image content does not change the timing)
foreach p {0 1 2 3} {
  foreach {kind mode} {fwd 5 back 6} {
    set n [ntok [file join $hw ${kind}_p$p.bin]]
    master_write_from_file $m [file join $hw ${kind}_p$p.bin] $SEV
    set nq [expr {$mode == 5 ? $n : 0}]
    set a [go $mode $n 0 0 1 0 $n $nq 1]
    set b [go $mode $n 0 0 $REP 0 [expr {$REP * $n}] [expr {$REP * $nq}] 1]
    puts "TIMING pass $p $kind tokens $n rep1 $a ms rep$REP $b ms"
  }
}
close_service master $m
