# kafka-efd-demo

DM uses Kafka to distribute messages from the LSST EFD (Engineering Facility Database) to subscribers like the DM-EFD and stream monitoring tools.
See [DMTN-082](https://dmtn-082.lsst.io/) for details of how this works.

![Diagram of the LSST EFD and DM-EFD components, showing Kafka as a glue between them.](https://dmtn-082.lsst.io/_images/dm-efd-concept.png)

This repository contains early explorations of deploying Kafka on Kubernetes and exercising the Kafka cluster with publishers, subscribers, and stream processors.
