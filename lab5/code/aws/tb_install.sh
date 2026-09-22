#!/bin/bash
# EE542 Lab5 — install ThingsBoard CE on a fresh Ubuntu 24.04 EC2 node.
# Runs ON the instance.  Invoke as:  sudo bash tb_install.sh <PGPASSWORD>
#
# Deviations from the handout, deliberate (record these in the report):
#   * handout says OpenJDK 17 + postgresql-16.  ThingsBoard 4.3.x recommends
#     OpenJDK 21, and the PGDG script now ships postgresql-18.  17 still meets
#     the floor but 21 is what upstream tests against.
#   * 4 GiB is the documented dev minimum and the install step is the memory
#     peak, so we add 4 GiB of swap first and cap the heap at 2 GiB, leaving
#     room for PostgreSQL.  Without this the install silently OOM-kills.
set -euxo pipefail
PGPW="${1:?usage: tb_install.sh <postgres-password>}"
TB_VER=4.3.1.5
export DEBIAN_FRONTEND=noninteractive

# --- swap: the install step is the memory peak on a 4 GiB box -----------------
if [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --- Java 21 ------------------------------------------------------------------
apt-get update
apt-get install -y openjdk-21-jdk-headless wget
update-alternatives --set java "/usr/lib/jvm/java-21-openjdk-$(dpkg --print-architecture)/bin/java"
java -version

# --- PostgreSQL ---------------------------------------------------------------
apt-get install -y postgresql-common
# -y, not `yes | ...`: when the PGDG script exits, `yes` takes SIGPIPE and
# under `set -o pipefail` that aborted the whole install right here.
/usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
apt-get update
apt-get install -y postgresql-18
systemctl enable --now postgresql
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD '${PGPW}';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='thingsboard'" \
  | grep -q 1 || sudo -u postgres psql -c "CREATE DATABASE thingsboard;"

# --- ThingsBoard CE -----------------------------------------------------------
cd /tmp
[ -f "thingsboard-${TB_VER}.deb" ] || \
  wget -q "https://github.com/thingsboard/thingsboard/releases/download/v${TB_VER}/thingsboard-${TB_VER}.deb"
dpkg -i "thingsboard-${TB_VER}.deb" || apt-get -f install -y

# Guard: this script is re-run after failures, and a second append would give
# thingsboard.conf two conflicting DB blocks.
if ! grep -q 'EE542 Lab5' /etc/thingsboard/conf/thingsboard.conf; then
cat >> /etc/thingsboard/conf/thingsboard.conf <<CONF
# --- EE542 Lab5 ---
export DATABASE_TS_TYPE=sql
export SPRING_DATASOURCE_URL=jdbc:postgresql://localhost:5432/thingsboard
export SPRING_DATASOURCE_USERNAME=postgres
export SPRING_DATASOURCE_PASSWORD=${PGPW}
export SQL_POSTGRES_TS_KV_PARTITIONING=MONTHS
export JAVA_OPTS="\$JAVA_OPTS -Xms1G -Xmx2G -Xss512k -XX:+AlwaysPreTouch"
CONF
fi

# --loadDemo seeds the tenant/customer accounts the handout logs in with.
if ! sudo -u postgres psql -d thingsboard -tc \
     "SELECT 1 FROM information_schema.tables WHERE table_name='tb_user'" | grep -q 1; then
  /usr/share/thingsboard/bin/install/install.sh --loadDemo
fi
systemctl enable --now thingsboard

echo "TB_INSTALL_DONE"
