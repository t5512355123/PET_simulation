#!/bin/bash
cd ~/claude_bsrem
for d in sys9 sys10; do
  echo -n "$d: $(tail -1 $d/full.out 2>/dev/null) sof=$(ls $d/output_files/*.sof 2>/dev/null | wc -l) "
done
echo "aocl=$(pgrep -c -f aocl-opt) q=$(pgrep -c -f quartus_)"
