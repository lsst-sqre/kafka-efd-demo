"""Transform text-formatted messages from the SAL into Avro-formatted
messages for Kafka connect.
"""

import datetime
import re

from kafkit.registry.serializer import PolySerializer


class SalTextTransformer:
    """A class that transforms text-formatted SAL messages to Avro.
    """

    preamble_pattern = re.compile(
        r"^(?P<topic_name>\w+):\( (?P<content>[\'\w\d\s,\.-]+)\)"
    )

    def __init__(self, registry):
        super().__init__()
        self._registry = registry
        self._serializer = PolySerializer(registry=self._registry)

    async def transform(self, key_text, message_text):
        """Transform the message to Confluent Wire Format Avro.
        """
        m = self.preamble_pattern.match(message_text)
        if m is None:
            raise RuntimeError('Cannot match topic name')

        topic_name = m.group('topic_name')
        items = [s.strip(" '") for s in m.group('content').split(',')]
        # The content of the message covered by the schema itself.
        data_items = items[6:]

        schema_info = await self._registry.get_schema_by_subject(
            topic_name, version='latest'
        )

        avro_data = {}

        sal_timestamp = datetime.datetime.fromtimestamp(
            float(items[2]), tz=datetime.timezone.utc)
        avro_data['kafka_timestamp'] = sal_timestamp

        scan_index = 0
        for schema_field in schema_info['schema']['fields']:
            print(schema_field)
            if 'sal_index' not in schema_field:
                continue
            field_data, scan_index = scan_field(
                schema_field, scan_index, data_items)
            avro_data[schema_field['name']] = field_data

        message = await self._serializer.serialize(
            avro_data,
            schema=schema_info['schema'],
            schema_id=schema_info['id'],
            subject=schema_info['subject'])
        return schema_info['schema']['name'], message


def scan_field(schema_field, scan_index, data_items):
    type_ = schema_field['type']
    if isinstance(type_, dict):
        if type_['type'] == 'long' and type_['type'] == 'timestamp-millis':
            return scan_timestamp_millis(schema_field, scan_index, data_items)
        elif type_['type'] == 'array':
            return scan_array(schema_field, scan_index, data_items)
        else:
            raise NotImplementedError(
                "Don't know how to scan this array field yet: "
                f"{schema_field!r}")
    elif type_ in ('float', 'double'):
        return scan_float(schema_field, scan_index, data_items)
    else:
        raise NotImplementedError(
            f"Don't know how to scan this field yet: {schema_field!r}")


def scan_float(schema_field, scan_index, data_items):
    return float(data_items[scan_index]), scan_index + 1


def scan_timestamp_millis(schema_field, scan_index, data_items):
    timestamp = float(data_items[scan_index]) / 1000.
    dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
    return dt, scan_index + 1


def scan_array(schema_field, scan_index, data_items):
    count = schema_field['type']['sal_count']
    item_type = schema_field['type']['items']
    if item_type in ('float', 'double'):
        array = [float(item)
                 for item in data_items[scan_index:scan_index+count]]
    elif item_type in ('int',):
        array = [int(item)
                 for item in data_items[scan_index:scan_index+count]]
    elif item_type in ('string',):
        array = [item
                 for item in data_items[scan_index:scan_index+count]]
    else:
        raise NotImplementedError(
            f"Can't scan an array of type {schema_field!r}")

    return array, scan_index + count
