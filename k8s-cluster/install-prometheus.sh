#!/usr/bin/env bash

set -x

# Install Prometheus and Grafana using TLS (see install-tiller.sh)
helm install stable/prometheus --name prometheus --tls
helm install stable/grafana --name grafana -f grafana.yaml --tls
