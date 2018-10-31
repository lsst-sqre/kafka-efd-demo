# kafka-efd-demo

DM uses Kafka to distribute messages from the LSST EFD (Engineering Facility Database) to subscribers like the DM-EFD and stream monitoring tools.
See [DMTN-082](https://dmtn-082.lsst.io/) for details of how this works.

![Diagram of the LSST EFD and DM-EFD components, showing Kafka as a glue between them.](https://dmtn-082.lsst.io/_images/dm-efd-concept.png)

This repository contains early explorations of deploying Kafka on Kubernetes and exercising the Kafka cluster with publishers, subscribers, and stream processors.

## Kubernetes cluster set up

1. `cd k8s-cluster`

2. The Kubernetes cluster is set up to these specs:

   - `n1-standard-2` machine type provides 2 vCPUs and 7.5 GB of memory (sufficient for JVM).
   - 3 nodes as a minimum for both the Zookeeper and Kafka clusters.
   - Enable VPC-native networking (alias IP). This makes it easier to connect to other Google services like Memorystore.
   - Disable Kubernetes Dashboard

   ```bash
   gcloud beta container clusters create "efd-kafka-1" --zone "us-central1-a" --username "admin" --cluster-version "1.9.7-gke.6" --machine-type "n1-standard-2" --image-type "COS" --disk-type "pd-standard" --disk-size "100" --scopes "https://www.googleapis.com/auth/compute","https://www.googleapis.com/auth/devstorage.read_only","https://www.googleapis.com/auth/logging.write","https://www.googleapis.com/auth/monitoring","https://www.googleapis.com/auth/servicecontrol","https://www.googleapis.com/auth/service.management.readonly","https://www.googleapis.com/auth/trace.append" --num-nodes "3" --enable-cloud-logging --enable-cloud-monitoring --enable-ip-alias "110" --addons HorizontalPodAutoscaling,HttpLoadBalancing --enable-autoupgrade --enable-autorepair
   ```

   **TODO:** script cluster creation.

3. Set up the cluster-admin role:

   ```bash
   ./create-cluster-admin.sh
   ```

4. Install Tiller

   ```bash
   install-tiller.sh
   ```

## Kafka cluster installation

From the `k8s-cluster/` directory, install the [Confluent Platform Kafka charts](https://github.com/confluentinc/cp-helm-charts):

```bash
./install-confluent-kafka.sh
```

See the [Confluent Platform Helm charts documentation](https://docs.confluent.io/current/installation/installing_cp/cp-helm-charts/docs/index.html) for more information.

## Test the Kafka cluster

Deploy a `kafka-client` pod:

```bash
kubectl create -f kafka-test-client-pod.yaml
```

Log into the `kafka-client` pod:

```bash
kubectl exec -it kafka-client -- /bin/bash
```

From the pod's shell,

1. Create a topic:

   ```bash
   kafka-topics --zookeeper confluent-kafka-cp-zookeeper-headless:2181 --topic confluent-kafka-topic --create --partitions 1 --replication-factor 1 --if-not-exists
   ```

2. Create a message:

   ```bash
   MESSAGE="`date -u`"
   ```

3. Produce a message to the topic:

   ```bash
   echo "$MESSAGE" | kafka-console-producer --broker-list confluent-kafka-cp-kafka-headless:9092 --topic confluent-kafka-topic
   ```

4. Consume the message:

   ```bash
   kafka-console-consumer --bootstrap-server confluent-kafka-cp-kafka-headless:9092 --topic confluent-kafka-topic --from-beginning --timeout-ms 2000 --max-messages 1 | grep "$MESSAGE"
   ```

### Related reading

- [jonbcampos/kubernetes-series](https://github.com/jonbcampos/kubernetes-series): scripts for creating a secure Helm/Tiller deployment. Goes with these Medium articles:

  - [Kubernetes: Day One](https://medium.com/google-cloud/kubernetes-day-one-30a80b5dcb29)
  - [Installing Helm in Google Kubernetes Engine (GKE)](https://medium.com/google-cloud/installing-helm-in-google-kubernetes-engine-7f07f43c536e)
  - [Install Secure Helm in Google Kubernetes Engine (GKE)](https://medium.com/google-cloud/install-secure-helm-in-gke-254d520061f7)
