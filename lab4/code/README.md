# EE 542 Lab 4 — Hadoop and Spark on EC2

Due **Friday Sep 26, 2026**. Group of 3.

Everything runs from a Mac against EC2 over `ssh`; no script is copied to a node
by hand. The same code also runs against a local two-node cluster in Docker,
which is how it was developed.

## Build and run

```bash
aws/lab4_cluster.sh up
setup/deploy.sh one
ssh ubuntu@$L4_MASTER_PUB 'corpus.sh fetch small && corpus.sh put small'
ssh ubuntu@$L4_MASTER_PUB 'spark/preload_jars.sh'
ssh ubuntu@$L4_MASTER_PUB 'NODES=1 bench/matrix.sh small'
setup/nodes.sh two
ssh ubuntu@$L4_MASTER_PUB 'NODES=2 bench/matrix.sh small'
aws/lab4_cluster.sh stop
```

`deploy.sh` installs JDK 11, Hadoop 3.3.6 and Spark 3.5.1 on both nodes, writes
`/etc/hosts`, distributes the master's ssh key, pushes `setup/conf/`, formats
HDFS and starts the daemons. It is re-runnable.

Single job, by hand:

```bash
mr/run_mr.sh wordcount|charcount|minmax <tier>
MASTER=yarn|'local[*]' spark/run_spark.sh wordcount|charcount|minmax <tier>
```

## Layout

```
aws/lab4_cluster.sh      two EC2 instances: up | ips | status | stop | start | down
setup/install_node.sh    JDK + Hadoop + Spark + environment, runs on a node
setup/deploy.sh          bare instances -> running cluster, runs on the Mac
setup/nodes.sh           one | two -- the whole of Section 3 is this file
setup/conf/              the four site XMLs the handout asks for and never gives
mr/*_mapper.py           wordcount, char, minmax (identity, for the second pass)
mr/*_reducer.py          streaming folds, not dict-of-everything
mr/run_mr.sh             one Streaming job, with -files and output cleanup
spark/spark_*.py         the three PySpark jobs; master comes from spark-submit
spark/preload_jars.sh    put Spark's jars on HDFS once (see below)
spark/run_spark.sh       one PySpark job on yarn or local[*]
corpus.sh                fetch tiny|small|large from a Gutenberg mirror, put to HDFS
bench/matrix.sh          the Section 6 grid -> CSV
local/                   two-node cluster in Docker, for development
```

## What is different from the handout, and why

The handout's code does not run as printed. Each fix is in the file it belongs
to with the reasoning inline; the short list:

| Handout | Problem | Here |
|---|---|---|
| security group opens 50070 | that is the Hadoop **2.x** NameNode UI; 3.3.6 serves 9870 | 9870 |
| `hadoop jar ... -mapper wordcount_mapper.py` | no `-files`, so the worker has no copy and every task on the second node dies | `-files` ships both scripts |
| `minmax_reducer.py` over `/gutenberg` | mapper output is all `word\t1`, so MIN and MAX are both 1 | second pass over the wordcount output, `-numReduceTasks 1` |
| `SparkContext("local", ...)` | pins Spark to one JVM, so Section 6's two-node question has no second arm | master comes from `spark-submit` |
| `sc.textFile("/gutenberg/*.txt")` | no scheme: under a local master that is the local filesystem, not HDFS | explicit `hdfs://master:9000` |
| Spark from `dlcdn.apache.org` | 404 | `archive.apache.org` |
| `SPARK_HOME=/usr/local/spark` | the tar command puts it in `/opt/spark` | `/opt/spark` |
| `echo "export PATH=$PATH:$SPARK_HOME/bin"` | double quotes expand at write time, and the quotes are typographic | single quotes, written by `install_node.sh` |
| re-run the jobs (Section 3) | a job whose output path exists fails before it starts | output removed first |
| t2.medium | burstable: a throttled run corrupts the only numbers the lab produces | c7i-flex.large |
| "use the Gutenberg dataset" | never says how many books, and corpus size decides Section 6's answer | `corpus.sh`, pinned ids, manifest per run |

One more that is not in the handout at all: `spark-submit` uploads
`/opt/spark/jars` into the application's staging directory on **every**
submission. Measured on the local harness, same job, two runs each: 13.3 s and
11.2 s with the jars preloaded on HDFS, 42.6 s and 35.2 s without. Timing Hadoop
against Spark without `spark/preload_jars.sh` measures a 300 MB file copy.

## Reproducing a number

Every row of `../data/raw/matrix.csv` comes from `bench/matrix.sh`, which
records two clocks per run: `wall_s`, what the user waits, and `yarn_ms`, the
application's own elapsed time from the ResourceManager REST API. The same
endpoint serves MapReduce and Spark applications, which is what makes the two
frameworks comparable rather than merely both timed.

The gap between the two clocks is fixed overhead: client JVM startup, the YARN
submission round trip, container allocation. On the small corpus it is most of
the total, which is why the `tiny` tier exists — one short book measures that
overhead alone, so the report can subtract it instead of reporting it as though
it were processing time.

## Local cluster (development, not measurement)

```bash
cd local
docker compose build
NODES=one docker compose up -d        # or NODES=two
docker compose exec master bash
docker compose down -v
```

Two containers on one Mac share cores and loopback networking, so **its timings
mean nothing** for the report. It is here so that a broken config, a missing
`-files`, or a mapper that crashes on a worker is found in thirty seconds
instead of on a paid instance. The containers install from the same URLs and
read the same `setup/conf/`, so a configuration that works there works on EC2.
