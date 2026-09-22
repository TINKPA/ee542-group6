#!/bin/bash
# Put Spark's jars on HDFS once, so spark-submit stops shipping them per run.
#
# Measured on the local two-node harness, spark-submit wall clock for the same
# wordcount over the small corpus, two runs each:
#
#   jars preloaded here      13.3 s, 11.2 s
#   handout default          42.6 s, 35.2 s
#
# The difference is /opt/spark/jars going into the application's staging
# directory on every single submission.  Timing the two frameworks without
# fixing this measures a 300 MB file copy, not Spark.  (The very first run
# after the upload is slower than both -- let the cache settle before timing.)
set -eu
[ -f /opt/lab4/env.sh ] && . /opt/lab4/env.sh
hdfs dfs -test -d /spark-jars && { echo "/spark-jars already present"; exit 0; }
hdfs dfs -mkdir -p /spark-jars
hdfs dfs -put "$SPARK_HOME"/jars/*.jar /spark-jars/
hdfs dfs -du -s -h /spark-jars
