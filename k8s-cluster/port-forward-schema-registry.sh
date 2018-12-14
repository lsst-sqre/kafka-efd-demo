#!/usr/bin/env bash

# Port forwarding Schema Registry to http://localhost:8081

set -x

echo "Port forwarding Schema Registry to http://localhost:8081"

POD_NAME=$(kubectl get pods --namespace default -l "app=cp-schema-registry,release=confluent-kafka" -o jsonpath="{.items[0].metadata.name}")
kubectl --namespace default port-forward $POD_NAME 8081
