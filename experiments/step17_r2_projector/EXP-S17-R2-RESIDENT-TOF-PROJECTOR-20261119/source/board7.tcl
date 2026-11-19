# System Console: EXP-S17 R2 (40 lanes x 4 sets, TOF, two resident copies) on D690 events.
# Usage: system-console --script=board7.tcl <hw7 dir> <rep>
set hw  [lindex $argv 0]
set REP [lindex $argv 1]
set SRC 0x00000000; set SIN 0x00020000; set SIO 0x00040000; set SEV 0x00100000; set SROW 0x00180000
set SNK 0x00010000; set KOUT 0x00060000; set KIO 0x00080000
set C_START 0x08; set C_STATUS 0x18; set DONE 0x2
set m [lindex [get_service_paths master] 0]
open_service master $m
puts "master: $m"
proc rd32 {a} { global m; return [master_read_32 $m $a 1] }
proc wr32 {a v} { global m; master_write_32 $m $a $v }
proc waitdone {base what} {
  global C_STATUS DONE
  set t0 [clock milliseconds]
  while {([rd32 [expr {$base + $C_STATUS}]] & $DONE) == 0} { if {[clock milliseconds] - $t0 > 600000} { puts "TIMEOUT $what"; exit 1 } }
  wr32 [expr {$base + $C_STATUS}] $DONE
}
proc go {mode nev cnt rep finit rs us zs nm nq raw} {
  global SRC SNK C_START
  wr32 [expr {$SNK + 0x20}] $nm; wr32 [expr {$SNK + 0x28}] $nq; wr32 [expr {$SNK + 0x30}] $raw
  wr32 [expr {$SNK + $C_START}] 1
  wr32 [expr {$SRC + 0x20}] $mode; wr32 [expr {$SRC + 0x28}] $nev; wr32 [expr {$SRC + 0x30}] 0; wr32 [expr {$SRC + 0x38}] $cnt
  wr32 [expr {$SRC + 0x40}] $rep; wr32 [expr {$SRC + 0x48}] $finit
  wr32 [expr {$SRC + 0x50}] $rs; wr32 [expr {$SRC + 0x58}] $us; wr32 [expr {$SRC + 0x60}] $zs
  set t0 [clock milliseconds]
  wr32 [expr {$SRC + $C_START}] 1
  waitdone $SNK sink
  set ms [expr {[clock milliseconds] - $t0}]
  waitdone $SRC src
  return $ms
}
proc go_off {mode off cnt} {
  global SRC SNK C_START
  wr32 [expr {$SNK + 0x20}] $cnt; wr32 [expr {$SNK + 0x28}] 0; wr32 [expr {$SNK + 0x30}] 0
  wr32 [expr {$SNK + $C_START}] 1
  wr32 [expr {$SRC + 0x20}] $mode; wr32 [expr {$SRC + 0x30}] $off; wr32 [expr {$SRC + 0x38}] $cnt
  wr32 [expr {$SRC + $C_START}] 1
  waitdone $SNK sink
  waitdone $SRC src
}
set fm [open [file join $hw meta.txt]]; set mt [read $fm]; close $fm
regexp {nev (\d+)} $mt -> NEV; regexp {nf (\d+)} $mt -> NF
# 1) ids, plane tables, TOF table (from io)
master_write_from_file $m [file join $hw rowt.bin] $SROW
puts "setid [go 4 0 0 1 0 0 0 0 1 0 0] ms"
master_write_from_file $m [file join $hw setup_io.bin] $SIO
set NSETUP [expr {[file size [file join $hw setup_io.bin]] / 24}]
puts "setup ($NSETUP entries) [go 7 0 $NSETUP 1 0 0 0 0 $NSETUP 0 0] ms"
set fi [open [file join $hw toftab_io.bin] rb]; fconfigure $fi -translation binary
for {set off 0} {$off < 1024} {incr off 512} {
  set f [open [file join $hw chunk.bin] wb]; fconfigure $f -translation binary
  puts -nonewline $f [read $fi [expr {8 * 512}]]; close $f
  master_write_from_file $m [file join $hw chunk.bin] $SIO
  wr32 [expr {$SRC + 0x30}] $off
  go_off 9 $off 512
}
close $fi
puts "TOF table loaded"
# 2) load the image (sweep chunks)
set fc [open [file join $hw chunks.txt]]; set chunks [split [string trim [read $fc]] "\n"]; close $fc
set fi [open [file join $hw img_sweep.bin] rb]; fconfigure $fi -translation binary
set t0 [clock milliseconds]
foreach ln $chunks {
  lassign $ln off r u z cnt
  set f [open [file join $hw chunk.bin] wb]; fconfigure $f -translation binary
  puts -nonewline $f [read $fi [expr {4 * $cnt}]]; close $f
  master_write_from_file $m [file join $hw chunk.bin] $SIO
  go 0 0 $cnt 1 0 $r $u $z $cnt 0 0
}
close $fi
puts "image loaded in [expr {[clock milliseconds] - $t0}] ms"
# 3) forward -> s
master_write_from_file $m [file join $hw ev7.bin] $SEV
puts "forward [go 5 $NEV 0 1 0 0 0 0 $NEV $NF 0] ms"
master_read_to_file $m [file join $hw board_s.bin] $KOUT [expr {4 * $NEV}]
# 4) clear, back
puts "clear [go 10 0 0 1 0 0 0 0 1 0 0] ms"
master_write_from_file $m [file join $hw board_s.bin] $SIN
puts "back [go 6 $NEV 0 1 0 0 0 0 $NEV 0 0] ms"
# 5) read back (sweep chunks)
set fo [open [file join $hw board_read.bin] wb]; fconfigure $fo -translation binary
foreach ln $chunks {
  lassign $ln off r u z cnt
  go 3 0 $cnt 1 0 $r $u $z $cnt $cnt 2
  master_read_to_file $m [file join $hw chunk.bin] $KIO [expr {4 * $cnt}]
  set f [open [file join $hw chunk.bin] rb]; fconfigure $f -translation binary
  puts -nonewline $fo [read $f]; close $f
}
close $fo
puts "read back done"
# 6) timing: forward and back passes, rep 1 vs rep REP
foreach {name mode nq} {fwd 5 1 back 6 0} {
  set q [expr {$nq ? $NEV : 0}]
  set a [go $mode $NEV 0 1 0 0 0 0 $NEV [expr {$nq ? $NF : 0}] 1]
  set b [go $mode $NEV 0 $REP 0 0 0 0 [expr {$REP * $NEV}] [expr {$nq ? $REP * $NF : 0}] 1]
  puts "TIMING $name tokens $NEV rep1 $a ms rep$REP $b ms"
}
close_service master $m
