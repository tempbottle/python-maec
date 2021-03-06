__version__ = "4.1.0.5"

import collections
import json
import inspect
import maec
from StringIO import StringIO
import bindings.maec_bundle as bundle_binding
import bindings.maec_package as package_binding
from cybox import Entity as cyboxEntity
from cybox import TypedField
from cybox.utils import Namespace
from maec.utils import maecMETA, EntityParser

def get_xmlns_string(ns_set):
    """Build a string with 'xmlns' definitions for every namespace in ns_set.

    Arguments:
    - ns_set: a set (or other iterable) of Namespace objects
    """
    xmlns_format = 'xmlns:{0.prefix}="{0.name}"'
    return "\n\t".join([xmlns_format.format(x) for x in ns_set if x])


def get_schemaloc_string(ns_set):
    """Build a "schemaLocation" string for every namespace in ns_set.

    Arguments:
    - ns_set: a set (or other iterable) of Namespace objects
    """
    schemaloc_format = '{0.name} {0.schema_location}'
    # Only include schemas that have a schema_location defined (for instance,
    # 'xsi' does not.
    return " ".join([schemaloc_format.format(x) for x in ns_set
                     if x and x.schema_location])

class Entity(object):
    """Base class for all classes in the MAEC SimpleAPI."""

    # By default (unless a particular subclass states otherwise), try to "cast"
    # invalid objects to the correct class using the constructor. Entity
    # subclasses should either provide a "sane" constructor or set this to
    # False.
    _try_cast = True

    def __init__(self):
        self._fields = {}

    @classmethod
    def _get_vars(cls):
        var_list = []
        for (name, obj) in inspect.getmembers(cls, inspect.isdatadescriptor):
            if isinstance(obj, TypedField):
                var_list.append(obj)

        return var_list

    def __eq__(self, other):
        # This fixes some strange behavior where an object isn't equal to
        # itself
        if other is self:
            return True

        # I'm not sure about this, if we want to compare exact classes or if
        # various subclasses will also do (I think not), but for now I'm going
        # to assume they must be equal. - GTB
        if self.__class__ != other.__class__:
            return False

        var_list = self.__class__._get_vars()

        # If there are no TypedFields, assume this class hasn't been
        # "TypedField"-ified, so we don't want these to inadvertently return
        # equal.
        if not var_list:
            return False

        for f in var_list:
            if not f.comparable:
                continue
            if getattr(self, f.attr_name) != getattr(other, f.attr_name):
                return False

        return True

    def __ne__(self, other):
        return not self == other

    def to_obj(self):
        """Default implementation of a to_obj function.

        Subclasses can override this function."""

        entity_obj = self._binding_class()

        for field in self.__class__._get_vars():
            val = getattr(self, field.attr_name)

            if field.multiple:
                 if val:
                     val = [x.to_obj() for x in val]
                 else:
                     val = []
            elif isinstance(val, Entity):
                val = val.to_obj()

            setattr(entity_obj, field.name, val)

        self._finalize_obj(entity_obj)

        return entity_obj

    def _finalize_obj(self, entity_obj):
        """Subclasses can define additional items in the binding object.

        `entity_obj` should be modified in place.
        """
        pass

    def to_dict(self):
        """Default implementation of a to_dict function.

        Subclasses can override this function."""

        entity_dict = {}

        for field in self.__class__._get_vars():
            val = getattr(self, field.attr_name)


            if field.multiple:
                 if val:
                     val = [x.to_dict() for x in val]
                 else:
                     val = []
            elif isinstance(val, Entity):
                val = val.to_dict()

            # Only add non-None objects or non-empty lists
            if val is not None and val != []:
                entity_dict[field.key_name] = val

        self._finalize_dict(entity_dict)

        return entity_dict

    def _finalize_dict(self, entity_dict):
        """Subclasses can define additional items in the dictionary.

        `entity_dict` should be modified in place.
        """
        pass

    @classmethod
    def from_obj(cls, cls_obj=None):
        if not cls_obj:
            return None

        entity = cls()

        for field in cls._get_vars():
            val = getattr(cls_obj, field.name)
            if field.type_:
                if field.multiple and val is not None:
                    val = [field.type_.from_obj(x) for x in val]
                else:
                    val = field.type_.from_obj(val)
            setattr(entity, field.attr_name, val)

        return entity

    @classmethod
    def from_dict(cls, cls_dict=None):
        if cls_dict is None:
            return None

        entity = cls()

        # Shortcut if an actual dict is not provided:
        if not isinstance(cls_dict, dict):
            value = cls_dict
            # Call the class's constructor
            try:
                return cls(value)
            except TypeError:
                raise TypeError("Could not instantiate a %s from a %s: %s" %
                                (cls, type(value), value))

        for field in cls._get_vars():
            val = cls_dict.get(field.key_name)
            if field.type_:
                if issubclass(field.type_, EntityList):
                    val = field.type_.from_list(val)
                elif field.multiple:
                    if val is not None:
                        val = [field.type_.from_dict(x) for x in val]
                    else:
                        val = []
                else:
                    val = field.type_.from_dict(val)

            else:
                 if field.multiple and not val:
                     val = []
            setattr(entity, field.attr_name, val)

        return entity

    def to_xml(self, include_namespaces=True, namespace_dict=None,
               pretty=True):
        """Export an object as an XML String.

        :param include_namespaces: whether to include xmlns and
          xsi:schemaLocation attributes on the root element. Set to true by
          default.
        :type include_namespaces: bool
        :param namespace_dict: mapping of additional XML namespaces to prefixes
        :type namespace_dict: dict
        :param pretty: produce readable (``True``) or compact (``False``)
          output. Default is ``True``
        :type pretty: bool
        """
        namespace_def = ""

        if include_namespaces:
            # Update the namespace dictionary with namespaces found upon import
            if namespace_dict and hasattr(self, '__input_namespaces__'):
                namespace_dict.update(self.__input_namespaces__)
            elif not namespace_dict and hasattr(self, '__input_namespaces__'):
                namespace_dict = self.__input_namespaces__
            namespace_def = self._get_namespace_def(namespace_dict)

        if not pretty:
            namespace_def = namespace_def.replace('\n\t', ' ')

        s = StringIO()
        self.to_obj().export(s, 0, namespacedef_=namespace_def,
                             pretty_print=pretty)
        return s.getvalue()

    def to_xml_file(self, filename, namespace_dict=None):
        """Export an object to an XML file. Only supports Package or Bundle objects at the moment."""
        # Update the namespace dictionary with namespaces found upon import
        if namespace_dict and hasattr(self, '__input_namespaces__'):
            namespace_dict.update(self.__input_namespaces__)
        elif not namespace_dict and hasattr(self, '__input_namespaces__'):
            namespace_dict = self.__input_namespaces__
        out_file  = open(filename, 'w')
        out_file.write("<?xml version='1.0' encoding='UTF-8'?>\n")
        self.to_obj().export(out_file, 0, namespacedef_ = self._get_namespace_def(namespace_dict))
        out_file.close()
         
    def to_json(self):
        """Export an object as a JSON string.
        """
        return json.dumps(self.to_dict())

    def _get_namespace_def(self, additional_ns_dict=None):
        # copy necessary namespaces

        namespaces = self._get_namespaces()

        # if there are any other namepaces, include xsi for "schemaLocation"
        # also, include the MAEC default vocabularies schema by default
        if namespaces:
            namespaces.update([maecMETA.lookup_prefix('xsi')])
            namespaces.update([maecMETA.lookup_prefix('maecVocabs')])

        if namespaces and additional_ns_dict:
            namespace_list = [x.name for x in namespaces if x]
            for ns, prefix in additional_ns_dict.iteritems():
                if ns not in namespace_list:
                    namespaces.update([Namespace(ns, prefix)])

        if not namespaces:
            return ""

        namespaces = sorted(namespaces, key=str)

        return ('\n\t' + get_xmlns_string(namespaces) +
                '\n\txsi:schemaLocation="' + get_schemaloc_string(namespaces) +
                '"')

    def _get_namespaces(self, recurse=True):
        nsset = set()

        # Get all _namespaces for parent classes
        namespaces = [x._namespace for x in self.__class__.__mro__
                      if hasattr(x, '_namespace')]

        nsset.update([maecMETA.lookup_namespace(ns) for ns in namespaces])

        #In case of recursive relationships, don't process this item twice
        self.touched = True
        if recurse:
            for x in self._get_children():
                if not hasattr(x, 'touched'):
                    nsset.update(x._get_namespaces())
        del self.touched

        return nsset

    def _get_children(self):
        #TODO: eventually everything should be in _fields, not the top level
        # of vars()
        for k, v in vars(self).items() + self._fields.items():
            if isinstance(v, Entity) or isinstance(v, cyboxEntity):
                yield v
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, Entity) or isinstance(item, cyboxEntity):
                        yield item

    @classmethod
    def istypeof(cls, obj):
        """Check if `cls` is the type of `obj`

        In the normal case, as implemented here, a simple isinstance check is
        used. However, there are more complex checks possible. For instance,
        EmailAddress.istypeof(obj) checks if obj is an Address object with
        a category of Address.CAT_EMAIL
        """
        return isinstance(obj, cls)


class EntityList(collections.MutableSequence, Entity):
    _contained_type = object

    # Don't try to cast list types (yet)
    _try_cast = False

    def __init__(self, *args):
        super(EntityList, self).__init__()
        self._inner = []

        for arg in args:
            if isinstance(arg, list):
                self.extend(arg)
            else:
                self.append(arg)

    def __getitem__(self, key):
        return self._inner.__getitem__(key)

    def __setitem__(self, key, value):
        if not self._is_valid(value):
            value = self._fix_value(value)
        self._inner.__setitem__(key, value)

    def __delitem__(self, key):
        self._inner.__delitem__(key)

    def __len__(self):
        return len(self._inner)

    def insert(self, idx, value):
        if not self._is_valid(value):
            value = self._fix_value(value)
        self._inner.insert(idx, value)

    def _is_valid(self, value):
        """Check if this is a valid object to add to the list.

        Subclasses can override this function, but it's probably better to
        modify the istypeof function on the _contained_type.
        """
        return self._contained_type.istypeof(value)

    def _fix_value(self, value):
        """Attempt to coerce value into the correct type.

        Subclasses can override this function.
        """
        try:
            new_value = self._contained_type(value)
        except:
            raise ValueError("Can't put '%s' (%s) into a %s" %
                (value, type(value), self.__class__))
        return new_value

    # The next four functions can be overridden, but otherwise define the
    # default behavior for EntityList subclasses which define the following
    # class-level members:
    # - _binding_class
    # - _binding_var
    # - _contained_type

    def to_obj(self):
        tmp_list = [x.to_obj() for x in self]

        list_obj = self._binding_class()

        setattr(list_obj, self._binding_var, tmp_list)

        return list_obj

    def to_list(self):
        return [h.to_dict() for h in self]

    # Alias the `to_list` function as `to_dict`
    to_dict = to_list

    @classmethod
    def from_obj(cls, list_obj):
        if not list_obj:
            return None

        list_ = cls()

        for item in getattr(list_obj, cls._binding_var):
            list_.append(cls._contained_type.from_obj(item))

        return list_

    @classmethod
    def from_list(cls, list_list):
        if not isinstance(list_list, list):
            return None

        list_ = cls()

        for item in list_list:
            list_.append(cls._contained_type.from_dict(item))

        return list_

    @classmethod
    def object_from_list(cls, entitylist_list):
        """Convert from list representation to object representation."""
        return cls.from_list(entitylist_list).to_obj()

    @classmethod
    def list_from_object(cls, entitylist_obj):
        """Convert from object representation to list representation."""
        return cls.from_obj(entitylist_obj).to_list()

def parse_xml_instance(filename, check_version = True):
    """Parse a MAEC instance and return the correct Binding and API objects
       Returns a dictionary of MAEC Package or Bundle Binding/API Objects"""
    object_dictionary = {}
    entity_parser = EntityParser()
    
    object_dictionary['binding'] = entity_parser.parse_xml_to_obj(filename, check_version)
    object_dictionary['api'] = entity_parser.parse_xml(filename, check_version)

    return object_dictionary
