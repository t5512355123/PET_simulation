# System Console: EXP-S15 slab v5 on Esser2 (4 passes) with images loaded / accumulators read over the DDR4 wide chain.
# Usage: system-console --script=board5.tcl <hw dir> <rep>
set hw  [lindex $argv 0]
set REP [lindex $argv 1]
set SRC 0x00000000; set SIN 0x00020000; set SIO 0x00040000; set SEV 0x00100000
set SNK 0x00010000; set KOUT 0x00060000; set KIO 0x00080000
set DIO 0x00200000; set LD 0x00210000; set ST 0x00220000; set DMA 0x00230000
set C_START 0x08; set C_STATUS 0x18; set DONE 0x2
set IMGB 0x0; set ACCB 0x100000; set PSTRIDE 0x20000
set m [lindex [get_service_paths master] 0]
open_service master $m
puts "master: $m"
proc rd32 {a} { global m; return [master_read_32 $m $a 1] }
proc wr32 {a v} { global m; master_write_32 $m $a $v }
proc waitdone {base what} {
  global C_STATUS DONE
  set t0 [clock milliseconds]
  while {([rd32 [expr {$base + $C_STATUS}]] & $DONE) == 0} {
    if {[clock milliseconds] - $t0 > 600000} { puts "TIMEOUT $what"; exit 1 }
  }
  wr32 [expr {$base + $C_STATUS}] $DONE
}
proc glue {args} { global hw; return [exec python3 [file join $hw .. .. glue4.py] {*}$args] }
proc pk {args} { global hw; return [exec python3 [file join $hw .. .. pack5.py] {*}$args] }
set NW [pk nwords]
puts "words per pass: $NW"
# event passes (as board4)
proc go {mode nev rep finit nm nq raw} {
  global SRC SNK C_START
  wr32 [expr {$SNK + 0x20}] $nm; wr32 [expr {$SNK + 0x28}] $nq; wr32 [expr {$SNK + 0x30}] $raw
  wr32 [expr {$SNK + $C_START}] 1
  wr32 [expr {$SRC + 0x20}] $mode; wr32 [expr {$SRC + 0x28}] $nev; wr32 [expr {$SRC + 0x30}] 0
  wr32 [expr {$SRC + 0x38}] 0; wr32 [expr {$SRC + 0x40}] $rep; wr32 [expr {$SRC + 0x48}] $finit
  set t0 [clock milliseconds]
  wr32 [expr {$SRC + $C_START}] 1
  waitdone $SNK sink
  set ms [expr {[clock milliseconds] - $t0}]
  waitdone $SRC src
  return $ms
}
# wide chain: start the storer (n words, ACC words to DDR word base sbase), then the loader (op, DDR word base lbase, rep)
proc wide {op lbase rep sbase} {
  global LD ST C_START NW
  wr32 [expr {$ST + 0x28}] 0; wr32 [expr {$ST + 0x2c}] 0
  wr32 [expr {$ST + 0x30}] [expr {$op == 3 ? 1 : $NW * $rep}]; wr32 [expr {$ST + 0x38}] $sbase
  wr32 [expr {$ST + $C_START}] 1
  wr32 [expr {$LD + 0x28}] 0; wr32 [expr {$LD + 0x2c}] 0
  wr32 [expr {$LD + 0x30}] $op; wr32 [expr {$LD + 0x38}] $lbase; wr32 [expr {$LD + 0x40}] $rep
  set t0 [clock milliseconds]
  wr32 [expr {$LD + $C_START}] 1
  waitdone $ST storer
  set ms [expr {[clock milliseconds] - $t0}]
  waitdone $LD loader
  return $ms
}
# host <-> DDR through the DMA (1024 words = 64 KB per chunk)
proc dma_to_ddr {file wbase} {
  global m DIO DMA C_START hw
  set fi [open $file rb]; fconfigure $fi -translation binary
  set n [expr {[file size $file] / 64}]
  for {set off 0} {$off < $n} {incr off 1024} {
    set c [expr {min(1024, $n - $off)}]
    set f [open [file join $hw chunk.bin] wb]; fconfigure $f -translation binary
    puts -nonewline $f [read $fi [expr {64 * $c}]]; close $f
    master_write_from_file $m [file join $hw chunk.bin] $DIO
    wr32 [expr {$DMA + 0x20}] 0; wr32 [expr {$DMA + 0x24}] 0
    wr32 [expr {$DMA + 0x28}] 0; wr32 [expr {$DMA + 0x30}] [expr {$wbase + $off}]; wr32 [expr {$DMA + 0x38}] $c
    wr32 [expr {$DMA + $C_START}] 1
    waitdone $DMA dma
  }
  close $fi
}
proc dma_from_ddr {file wbase n} {
  global m DIO DMA C_START hw
  set fo [open $file wb]; fconfigure $fo -translation binary
  for {set off 0} {$off < $n} {incr off 1024} {
    set c [expr {min(1024, $n - $off)}]
    wr32 [expr {$DMA + 0x20}] 0; wr32 [expr {$DMA + 0x24}] 0
    wr32 [expr {$DMA + 0x28}] 1; wr32 [expr {$DMA + 0x30}] [expr {$wbase + $off}]; wr32 [expr {$DMA + 0x38}] $c
    wr32 [expr {$DMA + $C_START}] 1
    waitdone $DMA dma
    master_read_to_file $m [file join $hw chunk.bin] $DIO [expr {64 * $c}]
    set f [open [file join $hw chunk.bin] rb]; fconfigure $f -translation binary
    puts -nonewline $fo [read $f]; close $f
  }
  close $fo
}
proc ntok {f} { return [expr {[file size $f] / 32}] }

puts "setid tokens [go 4 0 1 0 1 0 0] ms; setid wide ports [wide 3 0 1 0] ms"
set t0 [clock milliseconds]
foreach p {0 1 2 3} {
  pk pack $hw $p
  dma_to_ddr [file join $hw ddr_img_p$p.bin] [expr {$IMGB + $p * $PSTRIDE}]
}
puts "4 pass images written to DDR in [expr {[clock milliseconds] - $t0}] ms (JTAG)"
foreach ax {0 1} {
  set p0 [expr {2 * $ax}]; set p1 [expr {2 * $ax + 1}]
  puts "pass $p0 image load (DDR) [wide 1 [expr {$IMGB + $p0 * $PSTRIDE}] 1 0] ms"
  set n [ntok [file join $hw fwd_p$p0.bin]]
  master_write_from_file $m [file join $hw fwd_p$p0.bin] $SEV
  puts "pass $p0 forward (raw) [go 5 $n 1 0 $n $n 1] ms"
  master_read_to_file $m [file join $hw board_fwd_p$p0.bin] $KOUT [expr {4 * $n}]
  glue finit $hw $p0 $p1
  puts "pass $p1 image load (DDR) [wide 1 [expr {$IMGB + $p1 * $PSTRIDE}] 1 0] ms"
  set n [ntok [file join $hw fwd_p$p1.bin]]
  master_write_from_file $m [file join $hw fwd_p$p1.bin] $SEV
  master_write_from_file $m [file join $hw finit_p$p1.bin] $SIN
  puts "pass $p1 forward (ratio) [go 5 $n 1 1 $n $n 0] ms"
  master_read_to_file $m [file join $hw board_fwd_p$p1.bin] $KOUT [expr {4 * $n}]
  glue sback $hw $p1 $p0
  foreach p [list $p1 $p0] {
    set n [ntok [file join $hw back_p$p.bin]]
    master_write_from_file $m [file join $hw back_p$p.bin] $SEV
    master_write_from_file $m [file join $hw s_back_p$p.bin] $SIN
    puts "pass $p back [go 6 $n 1 0 $n 0 0] ms"
    puts "pass $p accumulator read (DDR) [wide 2 0 1 [expr {$ACCB + $p * $PSTRIDE}]] ms"
  }
}
foreach p {0 1 2 3} {
  dma_from_ddr [file join $hw board_accw_p$p.bin] [expr {$ACCB + $p * $PSTRIDE}] $NW
  pk unpack $hw $p
}
puts "accumulators copied back"
# timing of the wide chain: image load and accumulator read, rep 1 and rep REP
foreach {name op} {load 1 read 2} {
  set a [wide $op $IMGB 1 [expr {$ACCB + 4 * $PSTRIDE}]]
  set b [wide $op $IMGB $REP [expr {$ACCB + 4 * $PSTRIDE}]]
  puts "TIMING wide $name words $NW rep1 $a ms rep$REP $b ms"
}
close_service master $m
