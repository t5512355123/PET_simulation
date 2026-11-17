# timing probe: <ev file> <nev> <nf> <repA> <repB>
set evf [lindex $argv 0]; set NEV [lindex $argv 1]; set NF [lindex $argv 2]; set RA [lindex $argv 3]; set RB [lindex $argv 4]
set SRC 0x00000000; set SNK 0x00010000; set SEV 0x00100000
set m [lindex [get_service_paths master] 0]
open_service master $m
proc rd32 {a} { global m; return [master_read_32 $m $a 1] }
proc wr32 {a v} { global m; master_write_32 $m $a $v }
proc go {rep} {
  global SRC SNK NEV NF
  wr32 [expr {$SNK + 0x20}] [expr {2 * $rep * $NEV}]
  wr32 [expr {$SNK + 0x28}] [expr {$rep * $NF}]
  wr32 [expr {$SNK + 0x08}] 1
  wr32 [expr {$SRC + 0x20}] 1; wr32 [expr {$SRC + 0x28}] $NEV; wr32 [expr {$SRC + 0x40}] $rep
  set t0 [clock milliseconds]
  wr32 [expr {$SRC + 0x08}] 1
  while {([rd32 [expr {$SNK + 0x18}]] & 2) == 0} { if {[clock milliseconds] - $t0 > 300000} { puts TIMEOUT; exit 1 } }
  set ms [expr {[clock milliseconds] - $t0}]
  while {([rd32 [expr {$SRC + 0x18}]] & 2) == 0} {}
  wr32 [expr {$SNK + 0x18}] 2; wr32 [expr {$SRC + 0x18}] 2
  return $ms
}
master_write_from_file $m $evf $SEV
set a [go $RA]; set b [go $RB]
puts "PROBE $evf rep=$RA $a ms rep=$RB $b ms -> per pass [expr {double($b - $a) / ($RB - $RA)}] ms"
close_service master $m
