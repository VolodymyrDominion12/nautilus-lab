#!/bin/sh
# Refuse to publish an unlocked dashboard.
#
#   sh deploy/check_exposure.sh [deploy/.env]       exit 0 = safe to deploy
#
# The API token is compiled into the dashboard bundle (deploy/Dockerfile.web), so it
# does not protect the terminal from anyone who can load the page. What does:
#   * binding to localhost or a Tailscale address (100.64.0.0/10), or
#   * DASHBOARD_AUTH=on with BASIC_AUTH_USER + BASIC_AUTH_HASH (deploy/Caddyfile).
# Any other bind address (0.0.0.0, a public IP) with the lock off is refused.
# ALLOW_OPEN_DASHBOARD=1 overrides, for a deliberate choice only.
#
# Plain POSIX sh on purpose: it runs on the server before `docker compose up`.
set -u

ENV_FILE="${1:-deploy/.env}"

if [ ! -f "$ENV_FILE" ]; then
    echo "check_exposure: $ENV_FILE not found" >&2
    exit 2
fi

# Last assignment wins, as in compose. Surrounding single/double quotes are dropped;
# the value is never evaluated by the shell.
value_of() {
    sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" \
        | tail -n 1 \
        | sed -e "s/[[:space:]]*\$//" -e "s/^'\(.*\)'\$/\1/" -e 's/^"\(.*\)"$/\1/'
}

BIND_ADDR="$(value_of BIND_ADDR)"
SITE_ADDRESS="$(value_of SITE_ADDRESS)"
DASHBOARD_AUTH="$(value_of DASHBOARD_AUTH)"
BASIC_AUTH_USER="$(value_of BASIC_AUTH_USER)"
BASIC_AUTH_HASH="$(value_of BASIC_AUTH_HASH)"

# Same defaults as deploy/docker-compose.yml and deploy/Caddyfile.
BIND_ADDR="${BIND_ADDR:-127.0.0.1}"
SITE_ADDRESS="${SITE_ADDRESS:-:80}"
# Exactly `on`/`off`, lowercase: the Caddyfile imports the snippet `auth_<value>`, so
# `ON` would pass a case-insensitive check here and then fail inside Caddy.
DASHBOARD_AUTH="${DASHBOARD_AUTH:-off}"

case "$DASHBOARD_AUTH" in
    on | off) ;;
    *)
        echo "check_exposure: DASHBOARD_AUTH must be 'on' or 'off', got '$DASHBOARD_AUTH'" >&2
        exit 1
        ;;
esac

if [ "$DASHBOARD_AUTH" = "on" ]; then
    if [ -z "$BASIC_AUTH_USER" ] || [ -z "$BASIC_AUTH_HASH" ]; then
        echo "check_exposure: DASHBOARD_AUTH=on needs BASIC_AUTH_USER and BASIC_AUTH_HASH" >&2
        exit 1
    fi
    case "$BASIC_AUTH_HASH" in
        '$2'*) ;;
        *)
            echo "check_exposure: BASIC_AUTH_HASH is not a bcrypt hash (make one with" \
                "'caddy hash-password'; keep it in single quotes in $ENV_FILE)" >&2
            exit 1
            ;;
    esac
    echo "check_exposure: ok (basic auth on)"
    exit 0
fi

# 100.64.0.0/10 is Tailscale's range: second octet 64..127.
is_private_bind() {
    case "$1" in
        127.* | localhost) return 0 ;;
        100.*)
            second=$(echo "$1" | cut -d. -f2)
            case "$second" in
                '' | *[!0-9]*) return 1 ;;
            esac
            [ "$second" -ge 64 ] && [ "$second" -le 127 ]
            return
            ;;
    esac
    return 1
}

# The bind address is the firewall (Docker publishes around ufw), so it alone decides
# who can reach the page. A name in SITE_ADDRESS on a private bind — e.g. a
# `*.ts.net` MagicDNS name — is still reachable only from the tailnet.
if is_private_bind "$BIND_ADDR"; then
    echo "check_exposure: ok (bound to $BIND_ADDR, SITE_ADDRESS=$SITE_ADDRESS)"
    exit 0
fi
reasons="BIND_ADDR=$BIND_ADDR is reachable beyond localhost/Tailscale"

if [ "${ALLOW_OPEN_DASHBOARD:-0}" = "1" ]; then
    echo "check_exposure: WARNING — dashboard exposed without a lock ($reasons);" \
        "ALLOW_OPEN_DASHBOARD=1 set, continuing" >&2
    exit 0
fi

echo "check_exposure: refusing — $reasons, and DASHBOARD_AUTH=off." >&2
echo "  Anyone who loads the page gets the API token from the bundle and can drive" >&2
echo "  the paper sessions. Either bind to Tailscale (BIND_ADDR=100.x.y.z," >&2
echo "  SITE_ADDRESS=:80) or set DASHBOARD_AUTH=on with BASIC_AUTH_USER/BASIC_AUTH_HASH" >&2
echo "  in $ENV_FILE (see deploy/Caddyfile)." >&2
exit 1
