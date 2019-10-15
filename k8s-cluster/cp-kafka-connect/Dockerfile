# Builds a docker image for Confluent Platform Kafka Connect with InfluxDB Sink
# Connector from Landoop https://docs.lenses.io/connectors/sink/influx.html
# and adds the Oracle JDBC driver for the Confluent JDBC Sink connector

FROM confluentinc/cp-kafka-connect:latest

MAINTAINER afausti@lsst.org

# Add InfluxDB Sink Connector from Landoop

ARG CONNECTOR="influxdb"
ARG CONNECTOR_VERSION="1.2.3"
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
