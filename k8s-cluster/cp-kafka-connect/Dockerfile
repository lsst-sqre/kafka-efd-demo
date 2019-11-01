# Builds a docker image for Confluent Platform Kafka Connect with InfluxDB Sink
# Connector from Landoop https://docs.lenses.io/connectors/sink/influx.html
# and adds the Oracle JDBC driver for the Confluent JDBC Sink connector

ARG CONFLUENT_VERSION="5.3.1"
FROM confluentinc/cp-kafka-connect:${CONFLUENT_VERSION}

MAINTAINER afausti@lsst.org

# Add InfluxDB Sink Connector from Landoop

ARG CONNECTOR="influxdb"
ARG CONNECTOR_VERSION="1.2.1"
ARG VERSION="2.1.0"

RUN wget https://github.com/landoop/stream-reactor/releases/download/${CONNECTOR_VERSION}/kafka-connect-${CONNECTOR}-${CONNECTOR_VERSION}-${VERSION}-all.tar.gz && \
tar -xvf kafka-connect-${CONNECTOR}-${CONNECTOR_VERSION}-${VERSION}-all.tar.gz -C . && \
mkdir -p /etc/landoop/jars/lib && \
mv kafka-connect-${CONNECTOR}-${CONNECTOR_VERSION}-${VERSION}-all.jar /etc/landoop/jars/lib && \
chmod -R ag+w /etc/landoop/jars/lib

# Add the Oracle JDBC driver for the Confluent JDBC Sink Connector
# Download the Oracle JDBC driver (ojdbc8.jar) from
# https://www.oracle.com/technetwork/database/application-development/jdbc/downloads/index.html

COPY ./ojdbc8.jar /usr/share/java/kafka-connect-jdbc/

# Download the corresponding version of the Replicator connector from https://www.confluent.io/hub/confluentinc/kafka-connect-replicator 
RUN mkdir -p /usr/share/java/kafka-connect-replicator
COPY confluentinc-kafka-connect-replicator-${CONFLUENT_VERSION}/lib/* /usr/share/java/kafka-connect-replicator/ 
