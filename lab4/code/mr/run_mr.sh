#!/bin/bash
# Run one Hadoop Streaming job.  Runs on the master node.
#
# Usage: run_mr.sh wordcount|charcount|minmax <tier> [tag]
#
# Three things the handout's command line is missing:
#   -files          without it the worker has no copy of the mapper/reducer and
#                   every task on the second node dies (errata E-2)
#   -numReduceTasks 1 for minmax, which is a global extremum: with the default
#                   reducer count each task emits its own partition's MIN/MAX
#                   and the output contradicts itself (errata E-3)
#   deleting the output directory, because a job whose output path exists fails
#                   before it starts, and Section 3 asks you to re-run (E-10)
set -u
[ -f /opt/lab4/env.sh ] && . /opt/lab4/env.sh
DIR="$(cd "$(dirname "$0")" && pwd)"
JOB=${1:?job}; TIER=${2:?tier}; TAG=${3:-}
IN="/gutenberg_$TIER"
STREAMING=$(ls /usr/local/hadoop/share/hadoop/tools/lib/hadoop-streaming-*.jar | head -1)

run() {  # name mapper reducer input output [extra args...]
  local name=$1 mapper=$2 reducer=$3 in=$4 out=$5; shift 5
  hdfs dfs -rm -r -f "$out" >/dev/null 2>&1
  local t0 t1 log; log=$(mktemp)
  t0=$(date +%s.%N)
  hadoop jar "$STREAMING" \
    -files "$DIR/$mapper,$DIR/$reducer" \
    -input "$in" -output "$out" \
    -mapper "$mapper" -reducer "$reducer" "$@" 2>&1 | tee "$log"
  local rc=${PIPESTATUS[0]}
  t1=$(date +%s.%N)
  local app; app=$(grep -o 'application_[0-9_]*' "$log" | head -1)
  rm -f "$log"
  [ $rc -eq 0 ] || { echo "FAILED $name rc=$rc" >&2; return $rc; }
  echo "RESULT framework=mr job=$name tier=$TIER tag=$TAG app=$app wall_s=$(echo "$t1 - $t0" | bc)"
}

case "$JOB" in
wordcount)
  run wordcount wordcount_mapper.py wordcount_reducer.py "$IN" "/out_mr_wordcount_$TIER"
  ;;
charcount)
  run charcount char_mapper.py char_reducer.py "$IN" "/out_mr_charcount_$TIER"
  ;;
minmax)
  # Second pass over the wordcount output; the first pass is the input, not
  # the raw text (errata E-3).
  hdfs dfs -test -d "/out_mr_wordcount_$TIER" \
    || run wordcount wordcount_mapper.py wordcount_reducer.py "$IN" "/out_mr_wordcount_$TIER"
  run minmax minmax_mapper.py minmax_reducer.py \
    "/out_mr_wordcount_$TIER" "/out_mr_minmax_$TIER" -numReduceTasks 1
  ;;
*) echo "usage: run_mr.sh wordcount|charcount|minmax <tier> [tag]" >&2; exit 2 ;;
esac
