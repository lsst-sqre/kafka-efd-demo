#!/usr/bin/env bash

# Port forward the Prometheus server to http://localhost:9090

set -x

echo "Port forwarding Prometheus server to http://localhost:9090"

POD_NAME=$(kubectl get pods --namespace default -l "app=prometheus,component=server" -o jsonpath="{.items[0].metadata.name}")
kubectl --namespace default port-forward $POD_NAME 9090
