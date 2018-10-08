from plone.autoform.interfaces import IFormFieldProvider
from plone.supermodel import model
from zope import schema
from zope.i18nmessageid.message import MessageFactory
from zope.interface import provider

_ = MessageFactory("kombinat.behavior.collectionfilter")


@provider(IFormFieldProvider)
class ICollectionFilter(model.Schema):

    show_filter = schema.Bool(
        title=_(u"Show Filter"),
        description=_(
            "Show criteria filter in view and/or tile view of "
            "collective.cover"),
        default=False,
    )

    exclude_filter_values = schema.List(
        title=_(u"Exclude Filter Values"),
        description=_("Set default values with key:value[,value] per line"),
        default=[],
        required=False,
        value_type=schema.TextLine(),
    )

    default_filter_values = schema.List(
        title=_(u"Default Filter Values"),
        description=_("Set default values with key:value[,value] per line"),
        default=[],
        required=False,
        value_type=schema.TextLine(),
    )

    allow_empty_values_for = schema.List(
        title=_(u"Allow empty values for"),
        description=_(
            "help_allow_empty_values",
            default=u"Fieldnames provided here can be empty"),
        required=False,
        default=[],
        value_type=schema.TextLine(),
    )

    ignore_fields = schema.List(
        title=_(u"Ignore Fields"),
        description=_(
            "help_ignore_fields",
            default=u"Which fields should be ignored in the filter"),
        required=False,
        default=[],
        value_type=schema.TextLine(),
    )

    show_start = schema.Bool(
        title=_(u"Show 'Startdate' selector"),
        required=False,
        default=False,
    )

    model.fieldset('settings', fields=[
        'show_filter', 'default_filter_values', 'allow_empty_values_for',
        'show_start', 'ignore_fields'])
