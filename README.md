# kafka-efd-demo

DM uses Kafka to distribute messages from the LSST EFD (Engineering Facility Database) to subscribers like the DM-EFD and stream monitoring tools.
See [DMTN-082](https://dmtn-082.lsst.io/) for details of how this works.

![Diagram of the LSST EFD and DM-EFD components, showing Kafka as a glue between them.](https://dmtn-082.lsst.io/_images/dm-efd-concept.png)

This repository contains early explorations of deploying Kafka on Kubernetes and exercising the Kafka cluster with publishers, subscribers, and stream processors.

## Kubernetes cluster set up

1. The Kubernetes cluster is set up to these specs:

   - `n1-standard-2` machine type provides 2 vCPUs and 7.5 GB of memory (sufficient for JVM).
   - 3 nodes as a minimum for both the Zookeeper and Kafka clusters.
   - Enable VPC-native networking (alias IP). This makes it easier to connect to other Google services like Memorystore.
   - Disable Kubernetes Dashboard

   ```bash
   gcloud beta container clusters create "efd-kafka-1" --zone "us-central1-a" --username "admin" --cluster-version "1.9.7-gke.6" --machine-type "n1-standard-2" --image-type "COS" --disk-type "pd-standard" --disk-size "100" --scopes "https://www.googleapis.com/auth/compute","https://www.googleapis.com/auth/devstorage.read_only","https://www.googleapis.com/auth/logging.write","https://www.googleapis.com/auth/monitoring","https://www.googleapis.com/auth/servicecontrol","https://www.googleapis.com/auth/service.management.readonly","https://www.googleapis.com/auth/trace.append" --num-nodes "3" --enable-cloud-logging --enable-cloud-monitoring --enable-ip-alias "110" --addons HorizontalPodAutoscaling,HttpLoadBalancing --enable-autoupgrade --enable-autorepair
   ```

   **TODO:** script cluster creation.

2. Set up the cluster-admin role:

   ```bash
   ./k8s-cluster/create-cluster-admin.sh
   ```

### Related reading

- [jonbcampos/kubernetes-series](https://github.com/jonbcampos/kubernetes-series): scripts for creating a secure Helm/Tiller deployment. Goes with these Medium articles:

  - [Kubernetes: Day One](https://medium.com/google-cloud/kubernetes-day-one-30a80b5dcb29)
  - [Installing Helm in Google Kubernetes Engine (GKE)](https://medium.com/google-cloud/installing-helm-in-google-kubernetes-engine-7f07f43c536e)
  - [Install Secure Helm in Google Kubernetes Engine (GKE)](https://medium.com/google-cloud/install-secure-helm-in-gke-254d520061f7)
