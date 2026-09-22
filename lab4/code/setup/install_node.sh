#!/bin/bash
# Runs ON a node (both master and worker get the same install).
#
# Differences from the handout, all forced:
#   * Spark comes from archive.apache.org.  The handout's dlcdn URL is a 404
#     (errata E-14, re-checked 2026-09-21).
#   * SPARK_HOME is /opt/spark, which is where the handout's own tar command
#     puts it; the handout then exports /usr/local/spark (E-6).
#   * the .bashrc lines are single-quoted.  The handout double-quotes them, so
#     $PATH and $SPARK_HOME expand at write time -- $SPARK_HOME is not yet set,
#     so what lands in .bashrc is a PATH with an empty component (E-7).  Its
#     quotes are also typographic and would be written literally (E-8).
set -eu
HADOOP_VERSION=${HADOOP_VERSION:-3.3.6}
SPARK_VERSION=${SPARK_VERSION:-3.5.1}

sudo apt-get update
sudo apt-get install -y openjdk-11-jdk ssh rsync curl python3 bc

if [ ! -d /usr/local/hadoop ]; then
  wget -q "https://dlcdn.apache.org/hadoop/common/hadoop-${HADOOP_VERSION}/hadoop-${HADOOP_VERSION}.tar.gz"
  tar -xzf "hadoop-${HADOOP_VERSION}.tar.gz"
  sudo mv "hadoop-${HADOOP_VERSION}" /usr/local/hadoop
  rm -f "hadoop-${HADOOP_VERSION}.tar.gz"
fi

if [ ! -d /opt/spark ]; then
  wget -q "https://archive.apache.org/dist/spark/spark-${SPARK_VERSION}/spark-${SPARK_VERSION}-bin-hadoop3.tgz"
  tar -xzf "spark-${SPARK_VERSION}-bin-hadoop3.tgz"
  sudo mv "spark-${SPARK_VERSION}-bin-hadoop3" /opt/spark
  rm -f "spark-${SPARK_VERSION}-bin-hadoop3.tgz"
fi

sudo mkdir -p /data/hadoop /data/gutenberg /data/results
sudo chown -R "$USER" /data

JAVA=$(dirname "$(dirname "$(readlink -f "$(which javac)")")")
if ! grep -q 'EE542 lab4' ~/.bashrc; then
  cat >> ~/.bashrc <<'BASHRC'
# EE542 lab4
export JAVA_HOME=__JAVA__
export HADOOP_HOME=/usr/local/hadoop
export HADOOP_CONF_DIR=/usr/local/hadoop/etc/hadoop
export SPARK_HOME=/opt/spark
export PYSPARK_PYTHON=python3
export PATH=$PATH:$HADOOP_HOME/bin:$HADOOP_HOME/sbin:$SPARK_HOME/bin
BASHRC
  sed -i "s|__JAVA__|$JAVA|" ~/.bashrc
fi
# Anchored to the line start: the stock hadoop-env.sh ships a commented-out
# "# export JAVA_HOME=", which an unanchored grep matches, so the real export
# never gets written and every daemon dies with "JAVA_HOME is not set".
grep -q '^export JAVA_HOME' /usr/local/hadoop/etc/hadoop/hadoop-env.sh \
  || echo "export JAVA_HOME=$JAVA" >> /usr/local/hadoop/etc/hadoop/hadoop-env.sh

# Ubuntu's ~/.bashrc returns immediately for a non-interactive shell, so an
# `ssh host 'hdfs ...'` never sees the exports above.  Every node-side script
# sources this file instead.
cat > /opt/lab4/env.sh <<ENVSH
export JAVA_HOME=$JAVA
export HADOOP_HOME=/usr/local/hadoop
export HADOOP_CONF_DIR=/usr/local/hadoop/etc/hadoop
export SPARK_HOME=/opt/spark
export PYSPARK_PYTHON=python3
export PATH=\$PATH:/usr/local/hadoop/bin:/usr/local/hadoop/sbin:/opt/spark/bin
ENVSH
echo "installed on $(hostname): hadoop $HADOOP_VERSION, spark $SPARK_VERSION"
