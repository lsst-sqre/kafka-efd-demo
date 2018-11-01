#!/usr/bin/env bash

# Port forward the Prometheus Alertmanager to http://localhost:9093

set -x

echo "Port forwarding Prometheus Alertmanager to http://localhost:9093"

POD_NAME=$(kubectl get pods --namespace default -l "app=prometheus,component=alertmanager" -o jsonpath="{.items[0].metadata.name}")
kubectl --namespace default port-forward $POD_NAME 9093
