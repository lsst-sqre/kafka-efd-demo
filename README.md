# kafka-efd-demo

DM uses Kafka to distribute messages from the LSST EFD (Engineering Facility Database) to subscribers like the DM-EFD and stream monitoring tools.
See [DMTN-082](https://dmtn-082.lsst.io/) for details of how this works.

<img src="https://dmtn-082.lsst.io/_images/dm-efd-concept.png" width="600px" alt="Diagram of the LSST EFD and DM-EFD components, showing Kafka as a glue between them.">

This repository contains early explorations of deploying Kafka on Kubernetes and exercising the Kafka cluster with publishers, subscribers, and stream processors.

## Contents

- [Kubernetes cluster set up](#kubernetes-cluster-set-up)
- [Prometheus and Grafana installation](#prometheus-and-grafana-installation)
- [Kafka cluster installation](#kafka-cluster-installation)
- [InfluxDB installation (optional)](#influxdb-installation-optional)
- [Test the Kafka cluster](#test-the-kafka-cluster)
- [Connecting to Kafka via Telepresence](#connecting-to-kafka-via-telepresence)
- [The kafkaefd demo application](#the-kafkaefd-demo-application)
  - [kafkaefd admin — Kafka broker and topic administration](#kafkaefd-admin--kafka-broker-and-topic-administration)
  - [kafkaefd registry — Avro Schema Registry management](#kafkaefd-registry--avro-schema-registry-management)
  - [kafkaefd helloworld — Hello world demo](#kafkaefd-helloworld--hello-world-demo)
  - [kafkaefd helloavro — Hello world for Avro](#kafkaefd-helloavro--hello-world-for-avro)
  - [kafkaefd salschema — ts\_sal schema conversion](#kafkaefd-salschema--ts_sal-schema-conversion)
- [Experiments](#experiments)
  - [Mock SAL](#mock-sal)
  - [SAL Transformer](#sal-transformer)
- [Lessons learned](#lessons-learned)

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

## InfluxDB installation (optional)

Follow the [InfluxDB + Chronograf + Kapacitor (ICK) deployment](https://github.com/lsst-sqre/ick-deployment) instructions to install those components in the cluster.

### InfluxDB Sink Connector configuration

Configure the [Landoop InfluxDB Sink Connector](https://docs.lenses.io/connectors/sink/influx.html) to consume  Kafka Avro-serialized messages and write them to InfluxDB.

Create a database at InfluxDB:

```
curl -i -XPOST http://influxdb-influxdb:8086/query --data-urlencode "q=CREATE DATABASE kafkaefd"
```

Create and upload the connector configuration:

```
kafkaefd admin connectors create influxdb-sink --influxdb http://influxdb-influxdb:8086 --database kafkaefd --upload helloavro
```

Get the status of the new connector with:

```
kafkaefd admin connectors status influxdb-sink
{
    "connector": {
        "state": "RUNNING",
        "worker_id": "10.72.2.8:8083"
    },
    "name": "influxdb-sink",
    "tasks": [
        {
            "id": 0,
            "state": "RUNNING",
            "worker_id": "10.72.2.8:8083"
        }
    ],
    "type": "sink"
}
```

Finally produce a message for the `helloavro` topic:

```
kafkaefd helloavro produce "Hello Influx"
```

and verify that it was written to the InfluxDB database:

```
curl -XPOST http://influxdb-inlfuxdb:8086/query --data-urlencode "q=SELECT * from kafkaefd.autogen.helloavro"

{"results":[{"statement_id":0,"series":[{"name":"helloavro","columns":["time","content"],"values":[["2019-02-05T21:18:31.016246443Z","Hello Influx"]]}]}]}
```



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

To expose the Kafka brokers and Schema Registry locally, run this line in a local shell:

```bash
telepresence --run-shell --namespace default --also-proxy confluent-kafka-cp-kafka-headless --also-proxy confluent-kafka-cp-schema-registry
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

### kafkaefd admin — Kafka broker and topic administration

The `kafkaefd admin` command includes several subcommands that help administer a Kafka cluster and topics in it.

List topics:

```bash
kafkaefd admin topics list
```

Create a topic:

```bash
kafkaefd admin topics create topicname --partitions 3 --replication-factor 1
```

View, and optionally modify, configurations for a topic:

```bash
kafkaefd admin topics config topicname
kafkaefd admin topics config topicname --detail
kafkaefd admin topics config topicname --set retention.ms 86400000
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

### kafkaefd registry — Avro Schema Registry management

The `kafkaefd registry` command group is a full-service admin client for the [Confluent Schema Registry](https://docs.confluent.io/current/schema-registry/docs/index.html).
Schemas for Avro-formatted messages are automatically maintained in the schema registry.

List subjects (and optionally show details):

```bash
kafkaefd registry list --version --compatibility
```

Show a single version of a subject:

```bash
kafkaefd registry show subjectname  # defaults to latest
kafkaefd registry show subjectname --version 1
```

Test the compatibility of a schema file to a version of a subject:

```bash
kafkaefd registry test subjectname ./schema.avsc
kafkaefd registry test subjectname ./schema.avsc  --version 1
```

Upload a schema file for a subject:

```bash
kafkaefd registry upload subjectname ./schema.avsc
```

Delete a version (for development):

```bash
kafkaefd registry delete subjectname --version 1
```

Delete an entire subject (for development):

```bash
kafkaefd registry delete subjectname
```

Show the global compatibility configuration:

```bash
kafkaefd registry compat
```

Update the global compatibility configuration to one of `NONE`, 'FULL', 'FORWARD', `BACKWARD`:

```bash
kafkaefd registry compat --set BACKWARD
```

View and set the compatibility requirement for a specific subject:

```bash
kafkaefd registry compat --subject subjectname
kafkaefd registry compat --subject subjectname --set BACKWARD
```

### kafkaefd helloworld — Hello world demo

This is a simple example that shows how to send and receive plain text messages.

1. In one shell, run `telepresence`.

2. In a second shell, run the consumer:

   ```bash
   kafkaefd helloworld consume
   ```

3. In a third shell, fire off the producer:

   ```bash
   kafkaefd helloworld produce "Hello world"
   ```

   Do this repeatedly (and with different messages).
   You should see the consumer receive the messages.

In this hello world demo, the topic is `mytopic`, and by default all messages are created with a key of `hello`.

### kafkaefd helloavro — Hello world for Avro

The `kafkaefd helloavro` command group shows how to send and receive Avro-serialized messages.
These commands integrate with the Confluent Schema Registry deployed as part of the Helm deployment.

In this demo, the default topic is called `helloavro`.

1. In one shell, run `telepresence`.

2. In a second shell, start a consumer:

   ```bash
   kafkaefd helloavro consume
   ```

3. In a third shell, fire off a producer:

   ```bash
   kafkaefd helloavro produce "Hello world"
   ```

### kafkaefd salschema — ts\_sal schema conversion

The `kafkaefd salschema` command group includes commands for managing Avro translations of the Telescope & Site SAL schemas published at [https://github.com/lsst-ts/ts_xml](https://github.com/lsst-ts/ts_xml).

`kafkaefd salschema` currently uses the GitHub API to retrieve schemas from [ts_xml](https://github.com/lsst-ts/ts_xml).
Before running `kafkaefd salschema`, set up a GitHub Personal Access Token from https://github.com/settings/tokens and add them to the shell environment:

```bash
export GITHUB_USER="..."   # your GitHub username
export GITHUB_TOKEN="..."  # your personal access token
```

To convert the [ts_xml](https://github.com/lsst-ts/ts_xml) files into Avro, and persist those Avro schemas to a local directory `ts_xml_avro`, run:

```bash
kafkaefd salschema convert --write ts_xml_avro
```

See `kafkaefd salschema -h` for other options.
The `--xml-repo-ref` option, in particular, allows you to select a specific branch or tag of the [ts_xml](https://github.com/lsst-ts/ts_xml) repository for conversion.

## Experiments

The kafka-efd-demo includes several experimental applications that can be run at scale in Kubernetes.
This section describes those experiments.

### Mock SAL

This experiment creates mock messages of the actual SAL topics, though with random values.
The code is implemented in `kafkaefd.bin.salmock`.

This producer, by default, creates messages for the first 100 SAL topics (ordered alphabetically) at a rate of about 1 Hz.
Each SAL topic is an independent Kafka topic.
The name of the Kafka topic is a lower case version of the SAL topic with underscores replaced by dashes (`-`).

The schemas for the Kafka topics are in the Schema Registry.
The subject names for the schemas match the topic names, with a `-value` suffix.

#### 1. Add SAL schemas to the Registry

First, upload schemas from [ts_xml](https://github.com/lsst-ts/ts_xml) to the Schema Registry:

1. Set up `GITHUB_USER` and `GITHUB_TOKEN` as described in [kafkaefd salschema](#kafkaefd-salschema--ts_sal-schema-conversion).

2. Run:

   ```bash
   kafkaefd salschema convert --upload
   ```

#### 2. Deploy the producer

The producer is a Kubernetes job.
Deploy it:

```bash
kubectl apply -f k8s-apps/salmock-1node-100topic-1hz.yaml
```

Check the logs for the pod to verify that producers are up.

#### 3. Monitor production

Open http://localhost:9090 to view the Prometheus dashboard (use the `k8s-cluster/port-forward-prometheus.sh` script to set up port forwarding).

You can graph the overall message production rate the mock SAL job using this query:

```
rate(salmock_produced_total[5m])
```

### SAL Transformer

The SAL now writes messages to Kafka.
Those messages are formatted in plain text, though, based on a format similar to an SQL insert.
The InfluxDB ingest needs Avro-encoded messages, though.
To adapt these two systems together, the `kafkaefd saltransform` app is capable of consuming plain text messages from the SAL and converts them to Avro-formatted messages in new topics.

The original topics that SAL produces are named ``{{subsystem}}_{{kind}}`` where `subsystem` is the name of a SAL subsystem, and `kind` is one of `telemetry`, `events`, and `commands`.
For example: `MTM1M3TS_telemetry`.
Multiple SAL topics are written to each of these these Kafka topics.

The output topics are named after individual SAL topics, in an `lsst.sal` namespace.
For example, `lsst.sal.MTM1M3TS_thermalData`.
These topic names correspond to subject names for these schemas in the Schema Registry.

#### 1. Deploy the configuration

```
kubectl --namespace default apply -f k8s-apps/saltransformer-config.yaml
```

This configuration points to the Confluent installation deployed by [lsst-sqre/terraform-efd-kafka](https://github.com/lsst-sqre/terraform-efd-kafka), which is in the `kafka` Kubernetes namespace.
Change these hostnames as necessary.

#### 2. Deploy the topic and schema initialization

```
kubectl --namespace default apply -f k8s-apps/saltransformer-init.yaml
```

This is a Kubernetes Job that runs the `kafkaefd saltransform init` command.
For the specific subsytems, this command does the follow:

- Creates output topics for each SAL topic in the specified subsystems.
  These output topics are namespaced with a `lsst.sal` prefix.
  For example: `lsst.sal.MTM1M3TS_thermalData`.
  The command can be modified to control partitioning and replication factors.
  By default only 1 partition is created for a topic, but topics are replicated across all three brokers.

- Registers Avro schemas for each SAL topic in the specified subsystems with the Schema Registry.
  This does an XML to Avro conversion using the same code as [kafkaefd salschema](#kafkaefd-salschema--ts_sal-schema-conversion).

**Modify this job to add additional subsystems.**

#### 3. Deploy the transformer application

```
kubectl --namespace default apply -f k8s-apps/saltransformer-deployment.yaml
```

This deployment stands up the transformer applications themselves, `kafkaefd saltransformer run`.
With the structure of the `kafkaefd saltransformer run` application, a single container covers an entire subsystem (event, command, and telemetry streams).
Each subsystem has its own deployment so that containers for each subsystem are distributed across different nodes for performance.
If the input topics of a subsystem are partitioned, you can scale the number of replicas in that subsystem's transformer deployment.
For example, if the input topic `MTM1M3TS_telemetry` has three partitions, then the corresponding deployment for `MTM1M3TS` can have three replicas.

**Modify this deployment to add additional subsystems.**

#### Monitoring

The deployment generates Prometheus metrics for monitoring:

- `saltransform_produced` (counter) the number of messages processed. Can be used to compute a rate.

- `saltransform_total_seconds` (summary) observes the time, in seconds, to process a message, from consuming the original message to producing the transformed message.

- `saltransform_transform_seconds` (summary) observes the time, in seconds, to transform the message from text to Avro.
  That is, this metric only measures the processing time of `SalTextTransformer.transform`.

## Lessons learned

### Keys and partitioning

- Keys are hashed and the same key is always assigned to the same partition. Multiple keys can share the same partition (new partitions aren't automatically built). This means that a topic should be pre-populated with all the partitions it will ever need — never add partitions later.
- A message whose key is `None` is automatically load-balanced across the available partitions.

### Avro and Schema Registry

- [Terminology](https://docs.confluent.io/current/schema-registry/docs/schema_registry_tutorial.html#terminology):

  - A Kafka **topic** contains **messages**.
    A message is a key-value pair, and the key, message, or both, can be serialized as Avro.
  - A **schema** defines the structure of the Avro data format.
  - The Kafka topic name *can* be independent of the schema name.
  - A **subject** is defined in the Schema Registry as a scope where a schema can evolve.
    The name of the subject depends on the configured [subject name strategy](https://docs.confluent.io/current/schema-registry/docs/serializer-formatter.html#subject-name-strategy), which by default is set to derive subject name from topic name.

- By default, clients automatically register new schemas.
  In production, it's recommended that schemas should be registered outside of the producer app to provide control over schema evolution. To do this, set `auto.register.schemas=False`.
  See [Auto Schema Registration](https://docs.confluent.io/current/schema-registry/docs/schema_registry_tutorial.html#auto-schema-registration).

#### Further reading

- Confluent documentation: [Data Serialization and Evolution](https://docs.confluent.io/current/avro.html#data-serialization-and-evolution) (discusses Avro).

- [Confluent Schema Registry documentation](https://docs.confluent.io/current/schema-registry/docs/index.html)

- [Confluent Schema Registry RESTful API docs](https://docs.confluent.io/current/schema-registry/docs/api.html#schemaregistry-api)
