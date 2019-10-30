#!/bin/bash

usage(){
	echo "Usage: $0 SRC_BROKER DEST_BROKER DEST_SCHEMA_REGISTRY"
	exit 1
}

if [ "$1" == "" ] || [ "$2" == "" ] || [ "$3" == "" ]; then
    usage
fi

SRC_BROKER=$1
DEST_BROKER=$2
DEST_SCHEMA_REGISTRY=$3

echo '
{
   "name": "test-replicator",
   "config": {
     "connector.class": "io.confluent.connect.replicator.ReplicatorSourceConnector",
     "tasks.max": "4",
     "key.converter": "io.confluent.connect.replicator.util.ByteArrayConverter",
     "value.converter": "io.confluent.connect.replicator.util.ByteArrayConverter",
     "header.converter": "io.confluent.connect.replicator.util.ByteArrayConverter",
     "src.kafka.bootstrap.servers": "'${SRC_BROKER}'",
     "dest.kafka.bootstrap.servers": "'${DEST_BROKER}'",
     "topic.whitelist": "test-topic,_schemas",
     "topic.rename.format": "${topic}.replica",
     "schema.subject.translator.class": "io.confluent.connect.replicator.schemas.DefaultSubjectTranslator",
     "schema.registry.topic": "_schemas",
     "schema.registry.url": "'${DEST_SCHEMA_REGISTRY}'",
     "src.consumer.group.id": "test-replicator"
   }
 }'
