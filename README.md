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

### Related reading

- [jonbcampos/kubernetes-series](https://github.com/jonbcampos/kubernetes-series): scripts for creating a secure Helm/Tiller deployment. Goes with these Medium articles:

  - [Kubernetes: Day One](https://medium.com/google-cloud/kubernetes-day-one-30a80b5dcb29)
  - [Installing Helm in Google Kubernetes Engine (GKE)](https://medium.com/google-cloud/installing-helm-in-google-kubernetes-engine-7f07f43c536e)
  - [Install Secure Helm in Google Kubernetes Engine (GKE)](https://medium.com/google-cloud/install-secure-helm-in-gke-254d520061f7)

## Prometheus and Grafana installation

Install Prometheus and Grafana with Helm:

```bash
./install-prometheus.sh
```

Then access the various dashboards by port forwarding into the cluster:

- Connect to the Prometheus server:

  ```bash
  ./port-forward-prometheus.sh
  ```

  Open http://localhost:9090 in a browser.

- Connect to the Prometheus alert manager:

  ```bash
  ./port-forward-alertmanager.sh
  ```

  Open http://localhost:9093 in a browser.

- Connect to Grafana:

  ```bash
  ./port-forward-grafana.sh
  ```

  Open http://localhost:3000 in your browser.
  The username is "admin" and the password is printed by the port forwarding script.

  Import the [confluent-open-source-grafana-dashboard.json](https://github.com/confluentinc/cp-helm-charts/blob/700b4326352cf5220e66e6976064740b8c1976c7/grafana-dashboard/confluent-open-source-grafana-dashboard.json) dashboard into Grafana to monitor Kafka.

## Kafka cluster installation

From the `k8s-cluster/` directory, install the [Confluent Platform Kafka charts](https://github.com/confluentinc/cp-helm-charts):

```bash
./install-confluent-kafka.sh
```

### Related reading

- [Confluent Platform Helm charts documentation](https://docs.confluent.io/current/installation/installing_cp/cp-helm-charts/docs/index.html)
- [Confluent Platform Helm charts repository](https://github.com/confluentinc/cp-helm-charts)

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

## Connecting to Kafka via Telepresence

[Telepresence](https://www.telepresence.io) is a tool that proxies the Kubernetes network onto your local development machine.
For example, [Telepresennce](https://www.telepresence.io) lets a Kafka client, running locally, see and connect to all of the Kafka brokers.
This use useful for development since you can test client code from a local shell instead of waiting to deploy a container to the Kubernetes cluster.

To expose the Kafka brokers locally, run this line in a local shell:

```bash
telepresence --run-shell --namespace default --also-proxy confluent-kafka-cp-kafka-headless
```

Now you can run other Kafka clients in other shells.

### Related reading

- [Connecting to a Kafka cluster running in Kubernetes from outside](https://medium.com/@valercara/connecting-to-a-kafka-cluster-running-in-kubernetes-7601ae3a87d6)

## The kafkaefd demo application

This repository includes the kafkaefd Python packages, which includes the `kafkaefd` command-line client that implements several demonstration Kafka producers and consumers, as well as administrative commands.
Install the client in a Python 3.6+ virtual environment:

```bash
pip install -e .
```

Check that the command-line app is install

```bash
kafkaefd help
```

**Note:** The `--broker` option defaults to `confluent-kafka-cp-kafka-headless:9092`.
This is the headless service for the Kafka brokers given the Kubernetes/Helm installation described above.
This default should work both inside the cluster and via Telepresence.

### The kafkaefd admin command

The `kafkaefd admin` command includes several subcommands that help administer a Kafka cluster and topics in it.

List topics:

```bash
kafkaefd admin topics list
```

Create a topic:

```bash
kafkaefd admin topics create topicname --partitions 3 --replication-factor 1
```

Add partitions to a topic:

```bash
kafkaefd admin topics partition topicname 5
```

Delete a topic:

```bash
kafkaefd admin topics delete topicname
```

List brokers:

```bash
kafkaefd admin brokers
```

### Hello world demo

This is a simple example that shows how to send and receive plain text messages.

1. In one shell, run `telepresence`.

2. In a second shell, run the consumer:

   ```bash
   kafkaefd helloconsumer`
   ```

3. In a third shell, fire off the producer:

   ```bash
   kafkaefd helloproducer "Hello world"
   ```

   Do this repeatedly (and with different messages).
   You should see the consumer receive the messages.

In this hello world demo, the topic is `mytopic`, and by default all messages are created with a key of `hello`.

## Lessons learned

### Keys and partitioning

- Keys are hashed and the same key is always assigned to the same partition. Multiple keys can share the same partition (new partitions aren't automatically built). This means that a topic should be pre-populated with all the partitions it will ever need — never add partitions later.
- A message whose key is `None` is automatically load-balanced across the available partitions.
