#!/usr/bin/with-contenv bashio
set -e

CONFIG_PATH=/data/softener-gateway.yaml

if bashio::services.available "mqtt"; then
    export SOFTENER_GATEWAY_SUPERVISOR_MQTT_HOST
    export SOFTENER_GATEWAY_SUPERVISOR_MQTT_PORT
    export SOFTENER_GATEWAY_SUPERVISOR_MQTT_USERNAME
    export SOFTENER_GATEWAY_SUPERVISOR_MQTT_PASSWORD

    SOFTENER_GATEWAY_SUPERVISOR_MQTT_HOST="$(bashio::services mqtt "host")"
    SOFTENER_GATEWAY_SUPERVISOR_MQTT_PORT="$(bashio::services mqtt "port")"
    SOFTENER_GATEWAY_SUPERVISOR_MQTT_USERNAME="$(bashio::services mqtt "username")"
    SOFTENER_GATEWAY_SUPERVISOR_MQTT_PASSWORD="$(bashio::services mqtt "password")"
fi

python3 -m softener_gateway.ha_addon \
    --options /data/options.json \
    --output "${CONFIG_PATH}"

exec softener-gateway --config "${CONFIG_PATH}" -v
