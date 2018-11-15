#!/usr/bin/env bash

# Port forwarding Kafka Connect to http://localhost:8083

set -x

echo "Port forwarding Kafka Connect to http://localhost:8083"

POD_NAME=$(kubectl get pods --namespace default -l "app=cp-kafka-connect,release=confluent-kafka" -o jsonpath="{.items[0].metadata.name}")
kubectl --namespace default port-forward $POD_NAME 8083
