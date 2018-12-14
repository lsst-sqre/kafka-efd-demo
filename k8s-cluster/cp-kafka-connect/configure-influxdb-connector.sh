#!/usr/bin/env bash

# Configure InfluxDB Sink Connector from Landoop
# https://docs.lenses.io/connectors/sink/influx.html

set -x

echo "Configure InfluxDB Sink Connector from Landoop"
curl -s -X POST -H 'Content-Type: application/json' \
--data @$1 http://localhost:8083/connectors
