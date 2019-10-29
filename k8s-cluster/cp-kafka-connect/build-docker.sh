#!/usr/bin/env bash

IMAGE="lsstsqre/cp-kafka-connect"
IMAGE_TAG="5.3.1"

echo "Building Kafka Connect image"
docker build -t ${IMAGE}:${IMAGE_TAG} -f Dockerfile .
docker push ${IMAGE}:${IMAGE_TAG}
