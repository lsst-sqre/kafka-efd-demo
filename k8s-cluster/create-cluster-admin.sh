#!/usr/bin/env bash

# Creates the cluster-admin role and connects it the operator's Google account
# Based on https://github.com/jonbcampos/kubernetes-series/blob/master/helm/scripts/startup.sh
# https://medium.com/google-cloud/kubernetes-day-one-30a80b5dcb29

echo "create cluster administrator"
kubectl create clusterrolebinding cluster-admin-binding \
    --clusterrole=cluster-admin --user=$(gcloud config get-value account)
