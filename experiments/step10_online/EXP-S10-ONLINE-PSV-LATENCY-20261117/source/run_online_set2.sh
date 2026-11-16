PY="C:/Users/t5512/anaconda3/envs/pp/python.exe"
for cfg in "Br 32 256" "Br 64 64" "Br 16 64"; do
  set -- $cfg
  $PY online.py NeuroLF_Esser2 $1 $2 $3 on_$1_$2_$3.json > on_$1_$2_$3.log 2>&1
  echo "$cfg: $(grep -E 'after last event' on_$1_$2_$3.log)"
done
