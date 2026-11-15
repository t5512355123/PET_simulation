# System Console script: load image + events through JTAG, run the event lane, read back, compare.
# Usage: system-console --script=board_test.tcl <dir with ev.bin img.bin expect_*.bin> <csr_base> <ev_base> <s_base> <io_base>
set dir [lindex $argv 0]
set CSR [lindex $argv 1]
set EVB [lindex $argv 2]
set SB  [lindex $argv 3]
set IOB [lindex $argv 4]
# CSR word offsets from ev_lane_csr.h (filled in by the build script)
source [file join $dir csr_map.tcl]

set m [lindex [get_service_paths master] 0]
open_service master $m
puts "master: $m"

proc rd32 {a} { global m; return [master_read_32 $m $a 1] }
proc wr32 {a v} { global m; master_write_32 $m $a $v }
proc run_mode {mode nev off cnt {rep 1}} {
  global CSR CSR_MODE CSR_NEV CSR_OFF CSR_CNT CSR_REP CSR_START CSR_STATUS DONE_MASK
  wr32 [expr {$CSR + $CSR_MODE}] $mode
  wr32 [expr {$CSR + $CSR_NEV}] $nev
  wr32 [expr {$CSR + $CSR_OFF}] $off
  wr32 [expr {$CSR + $CSR_CNT}] $cnt
  wr32 [expr {$CSR + $CSR_REP}] $rep
  wr32 [expr {$CSR + $CSR_START}] 1
  set t0 [clock milliseconds]
  while {1} {
    set st [rd32 [expr {$CSR + $CSR_STATUS}]]
    if {($st & $DONE_MASK) != 0} break
    if {[clock milliseconds] - $t0 > 600000} { puts "TIMEOUT status=$st"; return -1 }
  }
  wr32 [expr {$CSR + $CSR_STATUS}] $DONE_MASK
  return [expr {[clock milliseconds] - $t0}]
}

set meta [open [file join $dir meta.txt]]; set mt [read $meta]; close $meta
regexp {nev (\d+)} $mt -> NEV
regexp {voxels (\d+)} $mt -> NVOX
regexp {
steps (\d+)} $mt -> STEPS
set CHUNK 16384

# 1) events
master_write_from_file $m [file join $dir ev.bin] $EVB
# 2) image, chunk by chunk through io
set fi [open [file join $dir img.bin] rb]
set t_load [clock milliseconds]
for {set off 0} {$off < $NVOX} {incr off $CHUNK} {
  set cnt [expr {min($CHUNK, $NVOX - $off)}]
  set f [open [file join $dir chunk.bin] wb]; puts -nonewline $f [read $fi [expr {4 * $cnt}]]; close $f
  master_write_from_file $m [file join $dir chunk.bin] $IOB
  run_mode 0 0 $off $cnt
}
close $fi
puts "image loaded in [expr {[clock milliseconds] - $t_load}] ms"
# 3) run the events
set ms [run_mode 1 $NEV 0 $STEPS]
puts "event batch done (JTAG-observed $ms ms, includes polling latency)"
# 4) read s and accumulator
master_read_to_file $m [file join $dir board_s.bin] $SB [expr {4 * $NEV}]
set fo [open [file join $dir board_acc.bin] wb]; close $fo
for {set off 0} {$off < $NVOX} {incr off $CHUNK} {
  set cnt [expr {min($CHUNK, $NVOX - $off)}]
  run_mode 2 0 $off $cnt
  master_read_to_file $m [file join $dir chunk_out.bin] $IOB [expr {4 * $cnt}]
  set a [open [file join $dir chunk_out.bin] rb]; set data [read $a]; close $a
  set fo [open [file join $dir board_acc.bin] ab]; puts -nonewline $fo $data; close $fo
}
puts "read back done"
# 5) timing: repeat the same batch REP times in one call, then read out (this also clears the accumulator)
set REP [expr {[llength $argv] > 5 ? [lindex $argv 5] : 2000}]
set ms [run_mode 1 $NEV 0 $STEPS $REP]
puts "TIMING rep=$REP wall_ms=$ms"
set fo [open [file join $dir board_acc_rep.bin] wb]; close $fo
for {set off 0} {$off < $NVOX} {incr off $CHUNK} {
  set cnt [expr {min($CHUNK, $NVOX - $off)}]
  run_mode 2 0 $off $cnt
  master_read_to_file $m [file join $dir chunk_out.bin] $IOB [expr {4 * $cnt}]
  set a [open [file join $dir chunk_out.bin] rb]; set data [read $a]; close $a
  set fo [open [file join $dir board_acc_rep.bin] ab]; puts -nonewline $fo $data; close $fo
}
close_service master $m
