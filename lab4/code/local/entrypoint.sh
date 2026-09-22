#!/bin/bash
# role = master | worker.  NODES = one | two selects which workers file to use.
set -e
ROLE=${1:?role}
NODES=${NODES:-one}

cp /opt/lab4/setup/conf/core-site.xml   "$HADOOP_CONF_DIR/"
cp /opt/lab4/setup/conf/hdfs-site.xml   "$HADOOP_CONF_DIR/"
cp /opt/lab4/setup/conf/mapred-site.xml "$HADOOP_CONF_DIR/"
cp /opt/lab4/setup/conf/yarn-site.xml   "$HADOOP_CONF_DIR/"
cp "/opt/lab4/setup/conf/workers.$NODES" "$HADOOP_CONF_DIR/workers"

mkdir -p /data/hadoop
/usr/sbin/sshd

if [ "$ROLE" = master ]; then
  [ -d /data/hadoop/nn/current ] || hdfs namenode -format -force -nonInteractive
  start-dfs.sh
  start-yarn.sh
  hdfs dfsadmin -safemode wait >/dev/null
  echo "=== cluster up (workers.$NODES) ==="
  hdfs dfsadmin -report | grep -E '^(Live datanodes|Name:)'
fi
tail -f /dev/null
