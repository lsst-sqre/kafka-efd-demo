FROM python:3.7.3
MAINTAINER sqre-admin
LABEL description="Publication service for LSST notebook-based reports" \
      name="lsstsqre/kafka-efd-demo"

USER root
RUN useradd -d /home/app -m app && \
    mkdir /dist

# Supply on CL as --build-arg VERSION=<version> (or run `make image`).
ARG        VERSION="0.0.1"
LABEL      version="$VERSION"
COPY       dist/kafkaefd-$VERSION.tar.gz /dist
RUN        pip install /dist/kafkaefd-$VERSION.tar.gz

USER app
WORKDIR /home/app

# Expose Prometheus metrics
EXPOSE 9092

CMD [ "kafkaefd", "--version" ]
