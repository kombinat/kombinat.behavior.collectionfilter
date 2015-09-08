from plone.autoform.interfaces import IFormFieldProvider
from plone.directives import form
from plone.supermodel import model
from zope import schema
from zope.i18nmessageid.message import MessageFactory
from zope.interface import provider

_ = MessageFactory("kombinat.behavior.collectionfilter")


@provider(IFormFieldProvider)
class ICollectionFilter(form.Schema):

    show_filter = schema.Bool(
        title=_(u"Show Filter"),
        description=_("Show criteria filter in view and/or tile view " \
            "of collective.cover"),
        default=False,
    )

    default_filter_values = schema.List(
        title=_(u"Default Filter Values"),
        description=_("Set default values with key:value in each line"),
        default=[],
        required=False,
        value_type=schema.TextLine(),
    )

    allow_empty_values_for = schema.List(
        title=_(u"Allow empty values for"),
        description=_("help_allow_empty_values",
            default=u"Fieldnames provided here can be empty"),
        required=False,
        default=[],
        value_type=schema.TextLine(),
    )

    show_start = schema.Bool(
        title=_(u"Show 'Startdate' selector"),
        required=False,
        default=False,
    )

    model.fieldset('settings', fields=['show_filter', 'default_filter_values',
        'allow_empty_values_for', 'show_start'])