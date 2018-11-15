# Builds a docker image for Confluent Platform Kafka Connect with InfluxDB Sink
# Connector from Landoop https://docs.lenses.io/connectors/sink/influx.html

FROM confluentinc/cp-kafka-connect-base

MAINTAINER afausti@lsst.org

ARG CONNECTOR
ARG CONNECTOR_VERSION

RUN echo "Installing InfluxDB Sink Connector from Landoop ..." && \
wget https://github.com/landoop/stream-reactor/releases/download/${CONNECTOR_VERSION}/kafka-connect-${CONNECTOR}-${CONNECTOR_VERSION}-${CONNECTOR_VERSION}-all.tar.gz && \
tar -xvf kafka-connect-${CONNECTOR}-${CONNECTOR_VERSION}-${CONNECTOR_VERSION}-all.tar.gz -C . && \
mkdir -p /etc/landoop/jars/lib && \
mv kafka-connect-${CONNECTOR}-${CONNECTOR_VERSION}-${CONNECTOR_VERSION}-all.jar /etc/landoop/jars/lib && \
chmod -R ag+w /etc/landoop/jars/lib
