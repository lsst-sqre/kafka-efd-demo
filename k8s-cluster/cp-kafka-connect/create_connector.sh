#!/usr/bin/env bash

set -x

echo "Create a kafka-connect connector"
curl -s -X POST -H 'Content-Type: application/json' \
--data @$1 http://confluent-cp-kafka-connect:8083/connectors
