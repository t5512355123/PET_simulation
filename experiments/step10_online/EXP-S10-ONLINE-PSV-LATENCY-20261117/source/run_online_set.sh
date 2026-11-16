PY="C:/Users/t5512/anaconda3/envs/pp/python.exe"
for cfg in "Br 32 64" "A 32 64" "A6 32 64" "B 32 16" "Br 32 16"; do
  set -- $cfg
  $PY online.py NeuroLF_Esser2 $1 $2 $3 on_$1_$2_$3.json > on_$1_$2_$3.log 2>&1
  echo "$cfg: $(grep -E 'after last event|post_proj_epochs|post_first_pass' on_$1_$2_$3.log | tr '\n' ' ')"
done
