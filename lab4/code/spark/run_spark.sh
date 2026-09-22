#!/bin/bash
# Run one PySpark job.  Runs on the master node.
#
# Usage: MASTER=yarn|local[*] run_spark.sh wordcount|charcount|minmax <tier> [tag]
#
# MASTER=yarn is the arm that actually uses both nodes.  MASTER='local[*]' keeps
# the handout's own configuration available as a third arm, which is worth
# measuring: the gap between the two is the cost of the cluster, and it is the
# honest way to show why the handout's script cannot answer Section 6.
set -u
[ -f /opt/lab4/env.sh ] && . /opt/lab4/env.sh
DIR="$(cd "$(dirname "$0")" && pwd)"
JOB=${1:?job}; TIER=${2:?tier}; TAG=${3:-}
MASTER=${MASTER:-yarn}
IN="/gutenberg_$TIER"
OUT="/out_spark_${JOB}_${TIER}"

case "$JOB" in wordcount|charcount|minmax) ;; *)
  echo "usage: run_spark.sh wordcount|charcount|minmax <tier> [tag]" >&2; exit 2 ;;
esac

hdfs dfs -rm -r -f "$OUT" >/dev/null 2>&1

# --py-files ships _common.py to the executors; without it a yarn run dies in
# the driver with ModuleNotFoundError.
SPARK_CONF=()
if [ "$MASTER" = yarn ]; then
  if hdfs dfs -test -d /spark-jars 2>/dev/null; then
    SPARK_CONF+=(--conf "spark.yarn.jars=hdfs:///spark-jars/*")
  else
    echo "WARNING: /spark-jars missing; this run will upload ~300 MB of jars and" >&2
    echo "         the time will not mean anything.  Run spark/preload_jars.sh." >&2
  fi
fi

t0=$(date +%s.%N)
spark-submit \
  --master "$MASTER" \
  "${SPARK_CONF[@]+"${SPARK_CONF[@]}"}" \
  --name "lab4-$JOB-$TIER" \
  --py-files "$DIR/_common.py" \
  "$DIR/spark_$JOB.py" "$IN" "$OUT"
rc=$?
t1=$(date +%s.%N)
[ $rc -eq 0 ] || { echo "FAILED spark/$JOB rc=$rc" >&2; exit $rc; }
echo "RESULT framework=spark-$(echo "$MASTER" | tr -d '[]*') job=$JOB tier=$TIER tag=$TAG submit_wall_s=$(echo "$t1 - $t0" | bc)"
