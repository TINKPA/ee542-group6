# Local two-node Hadoop + Spark cluster, for developing and testing the lab's
# code without paying for EC2.  It installs exactly what setup/install_hadoop.sh
# and setup/install_spark.sh install on the real nodes, from the same URLs, and
# it reads the same setup/conf/*.xml at runtime -- so a config that is wrong
# here is wrong on AWS too.
#
# Not a substitute for AWS for TIMING: two containers share one Mac's cores and
# loopback networking, so the numbers say nothing about a real two-node cluster.
# It is here to prove the jobs are correct and the configuration is complete.
FROM ubuntu:22.04

ARG HADOOP_VERSION=3.3.6
ARG SPARK_VERSION=3.5.1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      openjdk-11-jdk-headless python3 openssh-server openssh-client \
      curl wget bc procps rsync less ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN wget -q https://dlcdn.apache.org/hadoop/common/hadoop-${HADOOP_VERSION}/hadoop-${HADOOP_VERSION}.tar.gz \
    && tar -xzf hadoop-${HADOOP_VERSION}.tar.gz && mv hadoop-${HADOOP_VERSION} /usr/local/hadoop \
    && rm hadoop-${HADOOP_VERSION}.tar.gz

# archive.apache.org, not dlcdn: the handout's Spark URL is a 404 (errata E-14).
RUN wget -q https://archive.apache.org/dist/spark/spark-${SPARK_VERSION}/spark-${SPARK_VERSION}-bin-hadoop3.tgz \
    && tar -xzf spark-${SPARK_VERSION}-bin-hadoop3.tgz && mv spark-${SPARK_VERSION}-bin-hadoop3 /opt/spark \
    && rm spark-${SPARK_VERSION}-bin-hadoop3.tgz

ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-arm64 \
    HADOOP_HOME=/usr/local/hadoop \
    HADOOP_CONF_DIR=/usr/local/hadoop/etc/hadoop \
    SPARK_HOME=/opt/spark \
    PYSPARK_PYTHON=python3 \
    HDFS_NAMENODE_USER=root HDFS_DATANODE_USER=root HDFS_SECONDARYNAMENODE_USER=root \
    YARN_RESOURCEMANAGER_USER=root YARN_NODEMANAGER_USER=root
ENV PATH=$PATH:/usr/local/hadoop/bin:/usr/local/hadoop/sbin:/opt/spark/bin
RUN [ -d "$JAVA_HOME" ] || ln -s /usr/lib/jvm/java-11-openjdk-amd64 "$JAVA_HOME"

# Passwordless ssh master -> worker, which start-dfs.sh needs and the handout
# never mentions.
RUN ssh-keygen -q -t ed25519 -N '' -f /root/.ssh/id_ed25519 \
    && cp /root/.ssh/id_ed25519.pub /root/.ssh/authorized_keys \
    && printf 'Host *\n  StrictHostKeyChecking no\n  UserKnownHostsFile /dev/null\n  LogLevel ERROR\n' > /root/.ssh/config \
    && chmod 600 /root/.ssh/config && mkdir -p /run/sshd

RUN echo "export JAVA_HOME=$JAVA_HOME" >> /usr/local/hadoop/etc/hadoop/hadoop-env.sh

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
