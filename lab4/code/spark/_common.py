"""Shared entry point for the three PySpark jobs.

Two deliberate departures from the handout (errata E-4, E-5):

  * no SparkContext("local", ...).  Hardcoding the master pins every run to a
    single JVM on the submitting machine, so the second node never participates
    and Section 6's "on one node / on two nodes" question has no second arm.
    The master comes from spark-submit instead, which lets one script serve the
    yarn and local[*] arms of the comparison.
  * paths carry an explicit scheme.  sc.textFile("/gutenberg/*.txt") is not an
    HDFS path; with a local master it resolves against the local filesystem, so
    Spark and Hadoop would be reading different bytes and the comparison would
    be meaningless.
"""
import sys
import time

from pyspark import SparkContext

DEFAULT_FS = "hdfs://master:9000"


def start(name):
    if len(sys.argv) < 3:
        sys.exit(f"usage: {sys.argv[0]} <input> <output>   (paths may be bare, "
                 f"{DEFAULT_FS} is prepended)")
    sc = SparkContext(appName=name)
    inp, out = (p if "://" in p else DEFAULT_FS + p for p in sys.argv[1:3])
    return sc, inp, out, time.time()


def finish(sc, name, t0, extra=""):
    wall = time.time() - t0
    app = sc.applicationId
    master = sc.master
    sc.stop()
    print(f"RESULT framework=spark job={name} master={master} app={app} "
          f"wall_s={wall:.3f} {extra}".rstrip())
