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
        metadata_key = '_'.join(('sal', tag.lower()))
        _copy_xml_tag(avsc, root.find(tag), key=metadata_key)

    # The topic type itself is a special kind of metadata
    # (SALCommand, SALEvent, or SALTelemetry)
    avsc['sal_topic_type'] = root.tag

    # Convert fields
    for item in root.iterfind('item'):
        field = dict()

        _copy_xml_tag(field, item.find('EFDB_Name'), key='name')
        _copy_xml_tag(field, item.find('Description'), key='doc')
        _copy_xml_tag(field, item.find('Units'), key='sal_units')

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
                'symbols': enumeration.text.split(',')
            }

        elif count > 1:
            field['type'] = {'type': 'array', 'items': avro_type}

        else:
            field['type'] = avro_type

        avsc['fields'].append(field)

    if validate:
        validate_schema(avsc, raise_error=True)

    return avsc


def _copy_xml_tag(avro_obj, xml_tag, key=None):
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
    """
    if xml_tag is not None and xml_tag.text is not None:
        text = xml_tag.text.strip()  # filter empty strings
        if text:
            if key is None:
                # Use the tag's name as the Avro key itself
                key = xml_tag.tag
            avro_obj[key] = xml_tag.text


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
