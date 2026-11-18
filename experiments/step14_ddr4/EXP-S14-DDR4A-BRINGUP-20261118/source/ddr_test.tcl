# EXP-S14 board test: DDR4A write / verify / bandwidth through ddrbw (512-bit host at 150 MHz)
set m [lindex [get_service_paths master] 0]
open_service master $m
puts "master: $m"
proc rd32 {a} { global m; return [master_read_32 $m $a 1] }
proc wr32 {a v} { global m; master_write_32 $m $a $v }
proc run {mode n seed base} {
  wr32 0x28 [expr {$base & 0xffffffff}]; wr32 0x2c [expr {$base >> 32}]
  wr32 0x30 $mode; wr32 0x38 $n; wr32 0x40 $seed
  set t0 [clock milliseconds]
  wr32 0x08 1
  while {([rd32 0x18] & 2) == 0} { if {[clock milliseconds] - $t0 > 120000} { puts "TIMEOUT"; exit 1 } }
  set ms [expr {[clock milliseconds] - $t0}]
  set r [rd32 0x20]
  wr32 0x18 2
  return [list $ms $r]
}
# correctness at several regions (byte address = base + 64 * word)
foreach base {0x0 0x10000000 0x80000000 0xF0000000} {
  set w [run 0 65536 [expr {$base >> 20}] $base]
  set c [run 1 65536 [expr {$base >> 20}] $base]
  puts "VERIFY base $base: write [lindex $w 0] ms, mismatches [lindex $c 1]"
}
set c [run 1 65536 999 0x0]
puts "VERIFY wrong seed (expect many mismatches): [lindex $c 1]"
# bandwidth: n words of 64 B, two sizes, difference removes the JTAG start/poll overhead
foreach {mode name} {3 write 2 read} {
  set a [run $mode 1048576 0 0x0]
  set b [run $mode 16777216 0 0x0]
  set mb [expr {(16777216 - 1048576) * 64.0 / 1e6}]
  set ms [expr {[lindex $b 0] - [lindex $a 0]}]
  puts "BW $name: [lindex $a 0] ms (64 MB), [lindex $b 0] ms (1 GB) -> [format %.2f [expr {$mb / $ms}]] GB/s"
}
close_service master $m
