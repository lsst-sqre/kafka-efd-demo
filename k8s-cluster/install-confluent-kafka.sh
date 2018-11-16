#!/usr/bin/env bash

set -x

helm repo add confluentinc https://raw.githubusercontent.com/confluentinc/cp-helm-charts/master

helm repo update

# Install Kafka using TLS (see install-tiller.sh)
helm install -f cp-helm-charts-values.yaml confluentinc/cp-helm-charts --name confluent-kafka --tls
