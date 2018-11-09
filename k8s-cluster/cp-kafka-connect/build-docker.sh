#!/usr/bin/env bash

CONNECTOR="influxdb"
CONNECTOR_VERSION="1.1.0"
IMAGE="lsstsqre/cp-kafka-connect"
IMAGE_TAG="latest"

echo "Building CP Kafka Connect with InfluxDB Sink Connector from Landoop"
docker build \
    --build-arg CONNECTOR=${CONNECTOR} \
    --build-arg CONNECTOR_VERSION=${CONNECTOR_VERSION} \
    -t ${IMAGE}:${IMAGE_TAG} \
    -f Dockerfile .
docker push ${IMAGE}:${IMAGE_TAG}