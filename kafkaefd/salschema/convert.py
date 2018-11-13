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
        'name': root.find('EFDB_Topic').text,
        'fields': []
    }

    if root.find('Explanation') is not None:
        avsc['doc'] = root.find('Explanation').text

    # Add SAL metadata. These are keys that don't match to core Avro schema.
    root_metadata_tags = (
        'Subsystem',
        'Version',
        'Author',
        'Alias',
        'Device',
        'Property',
        'Action',
        'Value',
    )
    for tag in root_metadata_tags:
        if root.find(tag) is not None:
            metadata_key = '_'.join(('sal', tag.lower()))
            avsc[metadata_key] = root.find(tag).text

    # The topic type itself is a special kind of metadata
    # (SALCommand, SALEvent, or SALTelemetry)
    avsc['sal_topic_type'] = root.tag

    # Convert fields
    for item in root.iterfind('item'):
        field = {
            'name': item.find('EFDB_Name').text
        }

        if item.find('Description') is not None \
                and item.find('Description').text is not None:
            field['doc'] = item.find('Description').text

        count_tag = item.find('Count')
        if count_tag is not None:
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

        if item.find('Enumeration') is not None:
            field['type'] = {
                'type': 'enum',
                'name': field['name'],
                'symbols': item.find('Enumeration').text.split(',')
            }

        elif count > 1:
            field['type'] = {'type': 'array', 'items': avro_type}

        else:
            field['type'] = avro_type

        avsc['fields'].append(field)

    if validate:
        validate_schema(avsc, raise_error=True)

    return avsc


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
_SAL_TO_AVRO_TYPE['char'] = 'bytes'
_SAL_TO_AVRO_TYPE['octet'] = 'bytes'


def convert_ddl_to_avro_type_string(ddl_type):
    """Convert a DDL type string to an Avro type string.

    DDL type strings are used in the ``IDL_type`` tags of fields.
    """
    return _SAL_TO_AVRO_TYPE[ddl_type]
