#!/bin/bash
# EE542 Lab5 — put real TLS in front of ThingsBoard on the EC2 node.
# Runs ON the instance, after tb_install.sh:  sudo bash tb_tls.sh [hostname]
#
# Why this exists (errata E-6): OwnTracks for iOS ships
# NSAppTransportSecurity -> NSAllowsArbitraryLoads = false with no exception
# dictionary, so iOS refuses every plain http:// URL before a packet leaves the
# phone -- including a private-range LAN address.  The handout's whole
# http://<ip>:8080 endpoint is unreachable from an iPhone.  Android has no such
# restriction, so this script is what makes the lab work on mixed handsets.
#
# The hostname defaults to <public-ip>.sslip.io, a public wildcard-DNS service
# that resolves any <ip>.sslip.io to that IP.  That gives Let's Encrypt a real
# name to issue against with no domain purchase and no DNS edits, and the
# resulting certificate is one iOS already trusts -- unlike a self-signed cert,
# which ATS rejects the same way it rejects plaintext.
#
# Needs tcp 80 (ACME HTTP-01 challenge) and 443 open in the security group;
# aws_tb.sh opens both.
set -euxo pipefail

# IMDSv2: the token hop is required, the instance metadata role is not.
IMDS_TOKEN=$(curl -sX PUT http://169.254.169.254/latest/api/token \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
PUBIP=$(curl -s -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" \
  http://169.254.169.254/latest/meta-data/public-ipv4)
HOST="${1:-${PUBIP}.sslip.io}"
export DEBIAN_FRONTEND=noninteractive

# --- Caddy --------------------------------------------------------------------
# Caddy over nginx+certbot: certificate issuance and renewal are built in, so
# there is no second daemon and no cron entry to forget.
if ! command -v caddy >/dev/null; then
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main" \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y caddy
fi

# reverse_proxy passes Connection/Upgrade through untouched, so the ThingsBoard
# UI's /api/ws websocket survives the hop with no extra directive.
cat > /etc/caddy/Caddyfile <<CADDY
${HOST} {
	reverse_proxy 127.0.0.1:8080
}
CADDY

systemctl enable --now caddy
systemctl reload caddy || systemctl restart caddy

# --- wait for the certificate -------------------------------------------------
# Issuance is asynchronous: caddy answers :443 before the ACME order finishes,
# so polling the real endpoint is the only honest check.
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://${HOST}/login" || true)
  [ "$code" = "200" ] && { echo "TLS_OK https://${HOST}"; echo "TB_TLS_DONE"; exit 0; }
  sleep 5
done
echo "TLS_FAILED for ${HOST}; last code=${code}" >&2
journalctl -u caddy --no-pager -n 40 >&2
exit 1
