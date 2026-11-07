#!/bin/sh
set -e

if [ -n "$API_URL" ]; then
    TARGET_URL=$(echo "$API_URL" | sed -e 's:/api/*$::' -e 's:/*$::')
    case "$TARGET_URL" in
        http://*|https://*) ;;
        *) TARGET_URL="http://$TARGET_URL" ;;
    esac
    echo "[proofbox-web] Overriding API upstream to: $TARGET_URL"
    sed -i "s|proxy_pass http://api:8000;|proxy_pass $TARGET_URL;|g" /etc/nginx/conf.d/default.conf
fi
