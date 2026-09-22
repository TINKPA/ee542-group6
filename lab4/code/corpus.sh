#!/bin/bash
# Build a reproducible Gutenberg corpus ON A CLUSTER NODE and load it into HDFS.
#
# Runs on the master (over ssh on EC2, or docker exec in the local harness), not
# on the Mac: the large tier is ~1 GB and there is no reason to pull it across
# the wire twice, and the project shell is in iCloud.
#
# The handout never says which books or how many (errata E-13), yet corpus size
# is the independent variable of the whole Section 6 comparison.  So the set is
# pinned here and every run writes a manifest.
#
#   tiny    1 short book         measures fixed job overhead, nothing else
#   small   6 novels, ~4 MB      the handout's implied scale
#   large   ~1 GB                where shuffle actually costs something
#
# Usage: corpus.sh fetch tiny|small|large [target_mb]
#        corpus.sh put   tiny|small|large
set -u
[ -f /opt/lab4/env.sh ] && . /opt/lab4/env.sh
ROOT=${ROOT:-/data/gutenberg}
MIRROR=${MIRROR:-http://aleph.gutenberg.org}

SMALL_IDS="1342 11 84 1661 2701 98"
TINY_IDS="74"

mirror_path() {   # 1342 -> 1/3/4/1342
  local id=$1 p=""
  if [ ${#id} -eq 1 ]; then echo "0/$id"; return; fi
  for ((i=0; i<${#id}-1; i++)); do p="$p${id:$i:1}/"; done
  echo "$p$id"
}

fetch_one() {     # id destdir -> writes <id>.txt, prints bytes or nothing
  local id=$1 dir=$2 p; p=$(mirror_path "$id")
  for suffix in -0.txt .txt -8.txt; do
    if curl -sf --max-time 60 -o "$dir/$id.txt" "$MIRROR/$p/$id$suffix"; then
      [ -s "$dir/$id.txt" ] && { stat -c %s "$dir/$id.txt"; return 0; }
    fi
  done
  rm -f "$dir/$id.txt"
  return 1
}

case "${1:?usage: corpus.sh fetch|put <tier> [target_mb]}" in
fetch)
  TIER=${2:?tier}
  DIR="$ROOT/$TIER"; mkdir -p "$DIR"
  MANIFEST="$DIR/manifest.csv"; echo "id,bytes" > "$MANIFEST"
  case "$TIER" in
    tiny)  IDS="$TINY_IDS"; TARGET_MB=${3:-0} ;;
    small) IDS="$SMALL_IDS"; TARGET_MB=${3:-0} ;;
    large) IDS=""; TARGET_MB=${3:-1024} ;;
    *) echo "unknown tier $TIER" >&2; exit 2 ;;
  esac

  TOTAL=0
  for id in $IDS; do
    if B=$(fetch_one "$id" "$DIR"); then
      echo "$id,$B" >> "$MANIFEST"; TOTAL=$((TOTAL + B)); echo "  $id  $B"
    else
      echo "  $id  MISSING" >&2
    fi
  done

  # large: walk ids upward from a fixed start in parallel batches until the byte
  # target is met, so the set stays a deterministic function of (START,
  # TARGET_MB) while the download does not take hours.  Most ids in a range are
  # misses (each costs three probes), which is exactly why this is parallel:
  # measured sequentially it ran at roughly 1 book/s.
  if [ "$TIER" = large ]; then
    START=${START:-1}
    BATCH=${BATCH:-400}
    JOBS=${JOBS:-8}
    LIMIT=$((TARGET_MB * 1024 * 1024))
    export -f fetch_one mirror_path
    export MIRROR
    id=$START
    while [ $TOTAL -lt $LIMIT ] && [ $id -lt 60000 ]; do
      seq $id $((id + BATCH - 1)) | xargs -P "$JOBS" -I{} bash -c 'fetch_one "$@" >/dev/null 2>&1' _ {} "$DIR"
      id=$((id + BATCH))
      TOTAL=$(find "$DIR" -name '*.txt' -type f -exec stat -c %s {} + | awk '{s+=$1} END {print s+0}')
      echo "  through id $((id - 1)): $((TOTAL / 1024 / 1024)) MB"
    done
    : > "$MANIFEST"; echo "id,bytes" > "$MANIFEST"
    for f in "$DIR"/*.txt; do
      echo "$(basename "$f" .txt),$(stat -c %s "$f")" >> "$MANIFEST"
    done
  fi
  echo "$TIER: $(( $(wc -l < "$MANIFEST") - 1 )) books, $((TOTAL/1024/1024)) MB in $DIR"
  ;;

put)
  TIER=${2:?tier}
  DIR="$ROOT/$TIER"
  hdfs dfs -rm -r -f "/gutenberg_$TIER" >/dev/null 2>&1
  hdfs dfs -mkdir -p "/gutenberg_$TIER"

  # A thousand-odd books of ~0.5 MB each would be a thousand-odd input splits,
  # because a split never spans files: the job would spend its life starting
  # and stopping JVMs and we would be measuring Hadoop's small-file behaviour
  # instead of how the frameworks scale.  Concatenating into HDFS-block-sized
  # chunks first keeps the map count proportional to the data.  The small tier
  # is left alone -- it is meant to be small.
  if [ "$TIER" = large ]; then
    CHUNK_MB=${CHUNK_MB:-128}
    CHUNKS="$DIR/chunks"
    if [ ! -d "$CHUNKS" ]; then
      mkdir -p "$CHUNKS"
      # LARGE_MB caps the tier: the fetch overshoots (it only checks its byte
      # target between batches), and the experiment is sized for ~1 GB.
      LARGE_MB=${LARGE_MB:-1024}
      n=0; sz=0; total=0
      for f in "$DIR"/*.txt; do
        b=$(stat -c %s "$f")
        [ $((total + b)) -gt $((LARGE_MB * 1024 * 1024)) ] && break
        cat "$f" >> "$CHUNKS/part-$(printf %02d $n).txt"
        sz=$((sz + b)); total=$((total + b))
        if [ $sz -ge $((CHUNK_MB * 1024 * 1024)) ]; then n=$((n + 1)); sz=0; fi
      done
      echo "  chunked $((total / 1024 / 1024)) MB"
    fi
    echo "$(ls "$CHUNKS" | wc -l) chunks of ~${CHUNK_MB} MB"
    hdfs dfs -put "$CHUNKS"/*.txt "/gutenberg_$TIER/"
  else
    hdfs dfs -put "$DIR"/*.txt "/gutenberg_$TIER/"
  fi
  hdfs dfs -du -s -h "/gutenberg_$TIER"
  echo "files in HDFS: $(hdfs dfs -ls "/gutenberg_$TIER" | grep -c '^-')"
  ;;
*) echo "usage: corpus.sh fetch|put <tier> [target_mb]" >&2; exit 2 ;;
esac
