#!/usr/bin/env bash

set -x

echo "Remove a kafka-connect connector"
curl -s -X DELETE -H 'Content-Type: application/json' \
http://confluent-cp-kafka-connect:8083/connectors/$1
