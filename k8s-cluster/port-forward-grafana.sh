#!/usr/bin/env bash

# Port forward the Grafana server to http://localhost:3000

echo "Grafana admin password"
kubectl get secret --namespace default grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo

echo "Port forwarding Grafana to http://localhost:3000"
POD_NAME=$(kubectl get pods --namespace default -l "app=grafana" -o jsonpath="{.items[0].metadata.name}")
kubectl --namespace default port-forward $POD_NAME 3000
