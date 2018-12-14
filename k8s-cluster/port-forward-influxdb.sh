#!/usr/bin/env bash

# Port forwarding InfluxDB to http://localhost:8086

set -x

echo "Port forwarding InfluxDB to http://localhost:8086"

POD_NAME=$(kubectl get pods --namespace default -l "app=influxdb-influxdb,release=influxdb" -o jsonpath="{.items[0].metadata.name}")
kubectl --namespace default port-forward $POD_NAME 8086
