# System Console: slab projector board test (src + lanes + sink).
# Usage: system-console --script=board_test.tcl <data dir> <rep_a> <rep_b>
# data dir: ev.bin img.bin meta.txt
set dir  [lindex $argv 0]
set REPA [lindex $argv 1]
set REPB [lindex $argv 2]
# address map (slab_sys.tcl)
set SRC 0x00000000
set SIN 0x00020000
set SIO 0x00040000
set SEV 0x00100000
set SNK 0x00010000
set KOUT 0x00060000
set KIO 0x00080000
# CSR offsets (slab_src_csr.h, slab_sink_csr.h)
set C_START 0x08
set C_STATUS 0x18
set DONE 0x2
set S_MODE 0x20; set S_NEV 0x28; set S_OFF 0x30; set S_CNT 0x38; set S_REP 0x40
set K_NM 0x20; set K_NQ 0x28
set m [lindex [get_service_paths master] 0]
open_service master $m
puts "master: $m"
proc rd32 {a} { global m; return [master_read_32 $m $a 1] }
proc wr32 {a v} { global m; master_write_32 $m $a $v }
# start the sink (expects nm chain-1 tokens, nq chain-2 sums), then the source; wait for both
proc go {mode nev off cnt rep nm nq} {
  global SRC SNK C_START C_STATUS DONE S_MODE S_NEV S_OFF S_CNT S_REP K_NM K_NQ
  wr32 [expr {$SNK + $K_NM}] $nm
  wr32 [expr {$SNK + $K_NQ}] $nq
  wr32 [expr {$SNK + $C_START}] 1
  wr32 [expr {$SRC + $S_MODE}] $mode
  wr32 [expr {$SRC + $S_NEV}] $nev
  wr32 [expr {$SRC + $S_OFF}] $off
  wr32 [expr {$SRC + $S_CNT}] $cnt
  wr32 [expr {$SRC + $S_REP}] $rep
  set t0 [clock milliseconds]
  wr32 [expr {$SRC + $C_START}] 1
  while {1} {
    set st [rd32 [expr {$SNK + $C_STATUS}]]
    if {($st & $DONE) != 0} break
    if {[clock milliseconds] - $t0 > 600000} { puts "TIMEOUT mode=$mode sink=$st src=[rd32 [expr {$SRC + $C_STATUS}]]"; exit 1 }
  }
  set ms [expr {[clock milliseconds] - $t0}]
  while {([rd32 [expr {$SRC + $C_STATUS}]] & $DONE) == 0} {}
  wr32 [expr {$SNK + $C_STATUS}] $DONE
  wr32 [expr {$SRC + $C_STATUS}] $DONE
  return $ms
}
set fm [open [file join $dir meta.txt]]; set mt [read $fm]; close $fm
regexp {nev (\d+)} $mt -> NEV
regexp {nf (\d+)} $mt -> NF
regexp {voxels (\d+)} $mt -> NVOX
set CHUNK 16384

puts "setid [go 4 0 0 0 1 1 0] ms"
set fi [open [file join $dir img.bin] rb]; fconfigure $fi -translation binary
set t0 [clock milliseconds]
for {set off 0} {$off < $NVOX} {incr off $CHUNK} {
  set cnt [expr {min($CHUNK, $NVOX - $off)}]
  set f [open [file join $dir chunk.bin] wb]; fconfigure $f -translation binary
  puts -nonewline $f [read $fi [expr {4 * $cnt}]]; close $f
  master_write_from_file $m [file join $dir chunk.bin] $SIO
  go 0 0 $off $cnt 1 $cnt 0
}
close $fi
puts "image loaded in [expr {[clock milliseconds] - $t0}] ms"
master_write_from_file $m [file join $dir ev.bin] $SEV
puts "forward pass [go 5 $NEV 0 0 1 $NEV $NF] ms (JTAG-observed)"
master_read_to_file $m [file join $dir board_s.bin] $KOUT [expr {4 * $NEV}]
master_write_from_file $m [file join $dir board_s.bin] $SIN
puts "back pass [go 6 $NEV 0 0 1 $NEV 0] ms (JTAG-observed)"
set fo [open [file join $dir board_acc.bin] wb]; fconfigure $fo -translation binary
set t0 [clock milliseconds]
for {set off 0} {$off < $NVOX} {incr off $CHUNK} {
  set cnt [expr {min($CHUNK, $NVOX - $off)}]
  go 3 0 $off $cnt 1 $cnt 0
  master_read_to_file $m [file join $dir chunk.bin] $KIO [expr {4 * $cnt}]
  set f [open [file join $dir chunk.bin] rb]; fconfigure $f -translation binary
  puts -nonewline $fo [read $f]; close $f
}
close $fo
puts "accumulator read in [expr {[clock milliseconds] - $t0}] ms"
set ma [go 1 $NEV 0 0 $REPA [expr {2 * $REPA * $NEV}] [expr {$REPA * $NF}]]
set mb [go 1 $NEV 0 0 $REPB [expr {2 * $REPB * $NEV}] [expr {$REPB * $NF}]]
puts "TIMING rep=$REPA wall_ms=$ma rep=$REPB wall_ms=$mb"
close_service master $m
