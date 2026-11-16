# System Console: load voxel records, run the psv voxel unit, read the output, time REP passes.
# Usage: system-console --script=board_test.tcl <dir> <nz> <rep>
set dir [lindex $argv 0]
set NZ  [lindex $argv 1]
set REP [lindex $argv 2]
set MEM 0x00000000
set OMEM 0x00400000
set CSR 0x00500000
set m [lindex [get_service_paths master] 0]
open_service master $m
puts "master: $m"
proc wr32 {a v} { global m; master_write_32 $m $a $v }
proc rd32 {a} { global m; return [master_read_32 $m $a 1] }
proc f2u {f} { binary scan [binary format f $f] iu v; return $v }
proc run {mode rep} {
  global CSR NZ
  # CSR offsets from psv_update_csr.h (single host port version)
  wr32 [expr {$CSR + 0x20}] 0; wr32 [expr {$CSR + 0x24}] 0
  wr32 [expr {$CSR + 0x28}] 0; wr32 [expr {$CSR + 0x2c}] 0
  wr32 [expr {$CSR + 0x30}] $NZ
  wr32 [expr {$CSR + 0x38}] $mode
  wr32 [expr {$CSR + 0x40}] [f2u 8.0]
  wr32 [expr {$CSR + 0x48}] [f2u 1.0]
  wr32 [expr {$CSR + 0x50}] [f2u 3.5]
  wr32 [expr {$CSR + 0x58}] [f2u 0.2]
  wr32 [expr {$CSR + 0x60}] [f2u 0.001]
  wr32 [expr {$CSR + 0x68}] [f2u 2.0]
  wr32 [expr {$CSR + 0x70}] [f2u 1.0]
  wr32 [expr {$CSR + 0x78}] [f2u 0.70710678]
  wr32 [expr {$CSR + 0x80}] [f2u 0.57735027]
  wr32 [expr {$CSR + 0x88}] $rep
  wr32 [expr {$CSR + 0x08}] 1
  set t0 [clock milliseconds]
  while {1} {
    set st [rd32 [expr {$CSR + 0x18}]]
    if {($st & 0x2) != 0} break
    if {[clock milliseconds] - $t0 > 600000} { puts "TIMEOUT"; return -1 }
  }
  wr32 [expr {$CSR + 0x18}] 0x2
  return [expr {[clock milliseconds] - $t0}]
}
set t0 [clock milliseconds]
master_write_from_file $m [file join $dir rec.bin] $MEM
puts "records loaded in [expr {[clock milliseconds] - $t0}] ms"
set ms [run 0 1]
puts "single pass (JTAG-observed) $ms ms"
set nvox [expr {$NZ * 163 * 163}]
master_read_to_file $m [file join $dir board_out.bin] $OMEM [expr {8 * $nvox}]
set ms [run 0 $REP]
puts "TIMING rep=$REP wall_ms=$ms"
close_service master $m
