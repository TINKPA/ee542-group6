#!/bin/bash
# The Section 6 grid.  Runs on the master node; writes one CSV row per job run.
#
# Usage: NODES=1|2 REPS=3 matrix.sh <tier> [framework ...]
#        frameworks default to: mr spark-yarn spark-local
#
# Two clocks per run, and the difference between them is the point:
#
#   wall_s       what the user waits: client JVM start, submission, the job
#   yarn_ms      the application's own elapsed time, from the ResourceManager
#                REST API -- the same endpoint for MapReduce and for Spark,
#                which is what makes the two frameworks comparable at all
#
# Section 6 asks whether Spark's in-memory processing makes it faster.  At the
# handout's data scale most of the answer is fixed overhead, not processing, so
# a single total would let us "confirm" the expected answer without evidence.
# Run the tiny tier to measure that overhead on its own.
set -u
[ -f /opt/lab4/env.sh ] && . /opt/lab4/env.sh
DIR="$(cd "$(dirname "$0")" && pwd)"
TIER=${1:?usage: matrix.sh <tier> [framework ...]}; shift || true
FRAMEWORKS=${*:-mr spark-yarn spark-local}
NODES=${NODES:-1}
REPS=${REPS:-3}
JOBS=${JOBS:-wordcount charcount minmax}
RM=${RM:-http://master:8088}
OUT=${OUT:-/data/results}
CSV="$OUT/matrix.csv"

mkdir -p "$OUT"
[ -f "$CSV" ] || echo "ts,tier,nodes,framework,job,rep,wall_s,yarn_ms,app,extra" > "$CSV"

yarn_ms() {   # app id -> elapsed ms, or empty
  [ -n "${1:-}" ] || return 0
  curl -s --max-time 10 "$RM/ws/v1/cluster/apps/$1" \
    | python3 -c 'import json,sys
try: print(json.load(sys.stdin)["app"]["elapsedTime"])
except Exception: pass' 2>/dev/null
}

for fw in $FRAMEWORKS; do
  for job in $JOBS; do
    for rep in $(seq 1 "$REPS"); do
      submit=""
      case "$fw" in
        mr)
          line=$("$DIR/../mr/run_mr.sh" "$job" "$TIER" "n$NODES-r$rep" 2>/dev/null | grep '^RESULT')
          ;;
        spark-yarn|spark-local)
          [ "$fw" = spark-yarn ] && M=yarn || M='local[*]'
          all=$(MASTER="$M" "$DIR/../spark/run_spark.sh" "$job" "$TIER" "n$NODES-r$rep" 2>/dev/null | grep '^RESULT')
          # the in-application line carries the app id and the compute time;
          # the wrapper line carries submission overhead
          line=$(grep '^RESULT framework=spark ' <<<"$all")
          submit=$(sed -n 's/.*submit_wall_s=\([0-9.]*\).*/\1/p' <<<"$all")
          ;;
        *) echo "unknown framework $fw" >&2; exit 2 ;;
      esac
      if [ -z "$line" ]; then
        echo "$(date +%s),$TIER,$NODES,$fw,$job,$rep,,,,FAILED" >> "$CSV"
        echo "  $fw/$job rep$rep FAILED" >&2
        continue
      fi
      wall=$(sed -n 's/.*wall_s=\([0-9.]*\).*/\1/p' <<<"$line")
      app=$(sed -n 's/.*app=\(application_[0-9_]*\).*/\1/p' <<<"$line")
      extra=$(sed -n 's/.*\(min_scan_s=[0-9.]* max_scan_s=[0-9.]*\).*/\1/p' <<<"$line" | tr ' ' ';')
      [ -n "${submit:-}" ] && extra="submit_wall_s=${submit};${extra}"
      echo "$(date +%s),$TIER,$NODES,$fw,$job,$rep,$wall,$(yarn_ms "$app"),$app,$extra" >> "$CSV"
      echo "  $fw/$job rep$rep wall=${wall}s"
    done
  done
done
echo "--- $CSV ---"
command -v column >/dev/null && column -s, -t "$CSV" || cat "$CSV"
