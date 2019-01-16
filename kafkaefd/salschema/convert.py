"""Convert `ts_xml <https://github.com/lsst-ts/ts_xml>`_ SAL schemas to Avro.
"""

__all__ = ('convert_topic', 'validate_schema')

import json

import avro.schema


def convert_topic(root, validate=True):
    """Convert a SAL XML-formatted topic schema to an Avro schema.

    Parameters
    ----------
    validate : `bool`, optional
        If ``True``, the schema is validated before being returned.

    Returns
    -------
    schema : `dict`
        A `dict` object that can be serialized to JSON as an Avro schema
        (record type).

    Raises
    ------
    avro.schema.SchemaParseException
        Raised if the generated Avro schema is not valid.
    """
    avsc = {
        'type': 'record',
        'namespace': 'lsst.sal',
        'fields': []
    }

    _copy_xml_tag(avsc, root.find('EFDB_Topic'), key='name')
    _copy_xml_tag(avsc, root.find('Explanation'), key='doc')

    # Add SAL metadata. These are keys that don't match to core Avro schema.
    _copy_sal_metadata(avsc, root, ROOT_METADATA_TAGS)

    # The topic type itself is a special kind of metadata
    # (SALCommand, SALEvent, or SALTelemetry)
    avsc['sal_topic_type'] = root.tag

    # Add a timestamp field
    avsc['fields'].append({
        "name": "kafka_timestamp",
        "type": {"type": "long", "logicalType": "timestamp-millis"},
        "doc": "Timestamp when the Kafka message was created."
    })

    # Convert fields
    for index, item in enumerate(root.iterfind('item')):
        field = {
            # This is the index of the field in the XML schema.
            'sal_index': index
        }

        _copy_xml_tag(field, item.find('EFDB_Name'), key='name')
        _copy_xml_tag(field, item.find('Description'), key='doc')
        _copy_xml_tag(field, item.find('Units'), key='sal_units')

        _copy_sal_metadata(field, item, ITEM_METADATA_TAGS)

        count_tag = item.find('Count')
        if count_tag is not None and count_tag.text is not None:
            count = int(count_tag.text)
        else:
            count = 1  # default

        sal_type = item.find('IDL_Type').text
        try:
            avro_type = convert_ddl_to_avro_type_string(sal_type)
        except KeyError:
            raise RuntimeError(
                "Can't handle type {0} of field {1}.{2}".format(
                    sal_type, avsc['name'], field['name'])
                )

        enumeration = item.find('Enumeration')
        if enumeration is not None and enumeration.text is not None:
            field['type'] = {
                'type': 'enum',
                'name': field['name'],
                'symbols': [s.strip() for s in enumeration.text.split(',')]
            }

        elif count > 1:
            field['type'] = {'type': 'array', 'items': avro_type}

        else:
            field['type'] = avro_type

        avsc['fields'].append(field)

    if validate:
        validate_schema(avsc, raise_error=True)

    return avsc


def _copy_xml_tag(avro_obj, xml_tag, key=None, converter=None):
    """Copy an XML tag into an avro schema object

    Parameters
    ----------
    avro_obj : `dict`
        Schema object to copy the tag into. This object is modified in place.
    xml_tag : lxml element
        XML element, generated from ``root.find('tagname')``.
    key : `str`, optional
        Key to create in the ``avro_obj`` `dict`. If not set, the xml tag's
        name is used.
    converter : callable, optional
        Callable that takes the XML element's text value and converts it before
        insertion into the ``avro_obj``.
    """
    if xml_tag is not None and xml_tag.text is not None:
        text = xml_tag.text.strip()  # filter empty strings
        if text:
            if key is None:
                # Use the tag's name as the Avro key itself
                key = xml_tag.tag
            if converter is not None:
                avro_obj[key] = converter(text)
            else:
                avro_obj[key] = text


def _copy_sal_metadata(avro_obj, xml_root, tags):
    """Bulk copy and insert "metadata" tags from an XML element into the
    Avro schema.

    In the Avro schema, each metadata field if prefixed with ``"sal_"``,
    followed by the tag name in all lowercase characters.

    Parameters
    ----------
    avro_obj : `dict`
        Schema object to copy the tags into. This object is modified in place.
    xml_root : lxml element
        XML element to find and copy tags from.
    tags : `list` of `tuple`
        Each tuple has two elements:

        0. Name of the XML tag.
        1. Callable function that takes the tag's text value and converts it
           (such as converting strings to ints). Use `None` if no conversion
           is necessary.
    """
    for tag_name, converter in tags:
        key = '_'.join(('sal', tag_name.lower()))
        _copy_xml_tag(avro_obj,
                      xml_root.find(tag_name),
                      key=key,
                      converter=converter)


def _convert_sal_bool(value):
    """Convert a SAL XML schema boolean into a Python bool.
    """
    value = value.lower()
    if value == 'true':
        return True
    elif value == 'false':
        return False
    else:
        raise RuntimeError(
            'Incompatible value for boolean conversion: {0!r}'.format(value))


ROOT_METADATA_TAGS = (
    ('Subsystem', None),
    ('Version', None),
    ('Author', None),
    ('Alias', None),
    ('Device', None),
    ('Property', None),
    ('Action', None),
    ('Value', None),
)
"""Names of XML tags (and their conversion functions, if necessary) that are
copied from the root SALEvent, SALCommand, or SALTelemetry tag.
"""


ITEM_METADATA_TAGS = (
    ('Frequency', float),
    ('Publishers', int),
    ('Values_per_Publisher', int),
    ('Size_in_bytes', int),
    ('Conversion', None),
    ('Sensor_location', None),
    ('Instances_per_night', int),
    ('Bytes_per_night', int),
    ('Needed_by_DM', bool),
    ('Needed_by_Camera', _convert_sal_bool),
    ('Needed_by_OCS', _convert_sal_bool),
    ('Needed_by_TCS', _convert_sal_bool),
    ('Needed_by_EPO', _convert_sal_bool)
)
"""Names of XML tags (and their conversion functions, if necessary) that are
copied from item tags of SALEvent, SALCommand, or SALTelemetry elements.

This metadata is mostly used for SALTelemetry.
"""


def validate_schema(avsc, raise_error=False):
    """Validate a schema object

    Parameters
    ----------
    avsc : `dict`
        A `dict` that is JSON serializable.
    raise_error : `bool`
        If ``True``, an exception is raised for an invalid schema. By default,
        this function simply returns ``False`` for an invalid schema.

    Returns
    -------
    valid : `bool`
        `True` if the schema is valid as an Avro schema.

    Raises
    ------
    avro.schema.SchemaParseException
        Raised if the generated Avro schema is not valid and ``raise_error``
        is `True`.
    """
    try:
        avro.schema.SchemaFromJSONData(avsc)
    except avro.schema.SchemaParseException as e:
        print(json.dumps(avsc, indent=2, sort_keys=True))
        print(e)
        if raise_error:
            raise
        return False
    return True


_SAL_TO_AVRO_TYPE = {t: t for t in ('null', 'boolean', 'int', 'long', 'float',
                                    'double', 'bytes', 'string')}
_SAL_TO_AVRO_TYPE['short'] = 'int'
_SAL_TO_AVRO_TYPE['long long'] = 'long'
_SAL_TO_AVRO_TYPE['unsigned short'] = 'int'
_SAL_TO_AVRO_TYPE['unsigned int'] = 'int'
_SAL_TO_AVRO_TYPE['unsigned long'] = 'long'
_SAL_TO_AVRO_TYPE['byte'] = 'bytes'
_SAL_TO_AVRO_TYPE['unsigned long long'] = 'long'
_SAL_TO_AVRO_TYPE['char'] = 'bytes'
_SAL_TO_AVRO_TYPE['octet'] = 'bytes'


def convert_ddl_to_avro_type_string(ddl_type):
    """Convert a DDL type string to an Avro type string.

    DDL type strings are used in the ``IDL_type`` tags of fields.
    """
    return _SAL_TO_AVRO_TYPE[ddl_type]
