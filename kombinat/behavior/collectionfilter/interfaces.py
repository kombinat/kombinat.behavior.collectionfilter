from plone.app.contenttypes.interfaces import IPloneAppContenttypesLayer
from plone.app.event.interfaces import IBrowserLayer as IEventBrowserLayer
from zope.interface import Interface


class ICollectionFilterLayer(Interface):
    """ Layer Interface """


class ICollectionFilterEventLayer(IEventBrowserLayer):
    """ plone.app.event overrides """


class ICollectionFilterPACLayer(IPloneAppContenttypesLayer):
    """ override plone.app.contenttypes browserlayer views"""


class ICollectionFilter(Interface):
    """ interface for filter adapter """
