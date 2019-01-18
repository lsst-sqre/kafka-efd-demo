#!/usr/bin/env bash

set -x

helm repo add confluent https://confluentinc.github.io/cp-helm-charts/

helm repo update

# Install Kafka using TLS (see install-tiller.sh)
helm install -f cp-helm-charts-values.yaml confluent/cp-helm-charts --name confluent-kafka --tls
