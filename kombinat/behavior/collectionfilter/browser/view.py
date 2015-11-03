# -*- coding: utf-8 -*-
from DateTime import DateTime
from Products.AdvancedQuery import Between
from Products.AdvancedQuery import Ge
from Products.AdvancedQuery import Generic
from cStringIO import StringIO
from logging import getLogger
from plone import api
from plone.app.contentlisting.interfaces import IContentListing
from plone.app.contenttypes.browser.collection import CollectionView
from plone.app.event.base import RET_MODE_ACCESSORS
from plone.app.event.base import _prepare_range
from plone.app.event.base import expand_events
from plone.app.event.base import start_end_query
from plone.app.event.browser.event_listing import EventListing
from plone.app.layout.navigation.root import getNavigationRoot
from plone.app.querystring import queryparser
from plone.batching import Batch
from plone.dexterity.utils import safe_unicode
from plone.dexterity.utils import safe_utf8
from plone.memoize import ram
from plone.memoize.instance import memoizedproperty
from plone.memoize.view import memoize
import itertools

logger = getLogger(__name__)


class CollectionFilterQuery(object):

    def __init__(self):
        self.query = None

    def __iand__(self, val):
        if self.query is None:
            self.query = val
        else:
            self.query &= val
        return self

    def __ior__(self, val):
        if self.query is None:
            self.query = val
        else:
            self.query |= val
        return self


def _filtered_results_cachekey(fun, self, _q, sort_on, batch=False, b_size=100,
                               b_start=0):
    _ckey = StringIO()
    print >> _ckey, str(_q) + str(sort_on) + str(batch) + \
        str(b_size) + str(b_start)
    user = api.user.get_current()
    try:
        print >> _ckey, str(api.user.get_roles(user=user, obj=self.context))
    except api.exc.UserNotFoundError:
        pass
    return _ckey.getvalue()


class CollectionFilter(object):

    _ignored_keys = ('b_start', 'b_size', 'ajax_load', '_authenticator',
                     'start')
    _force_AND = ('path', 'portal_type')

    @memoizedproperty
    def default_values(self):
        dflt = self.context.default_filter_values
        if not dflt:
            return {}
        return dict([map(safe_unicode, l.split(":")) for l in dflt])

    @property
    def parsed_query(self):
        return queryparser.parseFormquery(self.context, self.context.query)

    def advanced_query(self, fdata):
        """
        FILTER QUERY
        the listing filter can contain arbitrary keyword indexes.
        special index is the 'portal_type' index, which is always AND
        concatenated... but (of course) only if defined in context.query

        2 Scenarios:

        1. search for kwx
        (kwx & kwx & ...) & portal_type

        2. Empty filter or search for portal_type only (!):
        (kw1 | kw2 | kwx | ...) & portal_type
        """
        _q = CollectionFilterQuery()
        pquery = self.parsed_query
        # setup default values and filter data
        fdata.update(dict([(k, v) for k, v in self.request.form.items() if v]))

        # fix pickadate value
        if fdata.get('_submit') is not None:
            fdata['start'] = fdata['_submit']
            del fdata['_submit']
        _allow_none = self.context.allow_empty_values_for or []
        _or_exclude = itertools.chain(
            self._ignored_keys, self._force_AND, _allow_none)

        # OR concatenation of default fields
        for idx in ([Generic(k, v['query']) for k, v in pquery.items() \
        if k not in _or_exclude]):
            if idx._idx == 'Subject':
                idx._term = map(safe_utf8, idx._term)
            _q |= idx

        def _subject_encode(k, v):
            return k == 'Subject' and safe_utf8(v) or safe_unicode(v)

        # AND concatenation of request values
        for idx in ([Generic(k, _subject_encode(k, v)) for k, v \
        in fdata.items() if v and k not in self._ignored_keys]):
            _q &= idx

        # special case for event listing filter
        if fdata.get('start'):
            st = DateTime(fdata.get('start')).earliestTime()
            se = DateTime(fdata.get('start')).latestTime()
            _q &= Between('start', st, se)
        elif pquery.get('start'):
            try:
                st = DateTime(pquery['start']['query'].strftime(
                    '%Y-%m-%d %H:%M')).asdatetime()
                _q &= Ge('start', st)
            except TypeError:
                pass

        if fdata.get('portal_type') or pquery.get('portal_type'):
            _q &= Generic('portal_type', fdata.get('portal_type') or \
                pquery.get('portal_type'))

        # respect INavigationRoot or ILanguageRootFolder or ISubsite
        _q &= Generic('path', fdata.get('path') or pquery.get('path') or \
            getNavigationRoot(self.context))

        return _q.query

    def filtered_result(self, **kwargs):
        if 'default_values' in kwargs:
            fdata = kwargs.pop('default_values')
        else:
            fdata = self.default_values

        _q = self.advanced_query(fdata)
        sort_on = ((getattr(self.context, 'sort_on', 'sortable_title'),
            self.context.sort_reversed and 'desc' or 'asc'), )
        try:
            return self._eval_advanced_query(
                _q, sort_on, kwargs.get('batch', False),
                kwargs.get('b_size', 100), kwargs.get('b_start', 0))
        except Exception, msg:
            logger.info("Could not apply filtered search: {}, {} {}".format(
                msg, fdata, _q))

        # fallback to default
        return self.collection_behavior.results(**kwargs)

    @ram.cache(_filtered_results_cachekey)
    def _eval_advanced_query(self, _q, sort_on, batch=False, b_size=100,
                             b_start=0):
        logger.info(_q)
        _res = self.context.portal_catalog.evalAdvancedQuery(_q, sort_on)
        listing = IContentListing(_res)
        if batch:
            return Batch(listing, b_size, start=b_start)
        return listing


class FilteredCollectionView(CollectionFilter, CollectionView):

    b_size = 100

    def results(self, **kwargs):
        """Return a content listing based result set with results from the
        collection query.

        :param **kwargs: Any keyword argument, which can be used for catalog
                         queries.
        :type  **kwargs: keyword argument

        :returns: plone.app.contentlisting based result set.
        :rtype: ``plone.app.contentlisting.interfaces.IContentListing`` based
                sequence.
        """
        # Extra filter
        contentFilter = self.request.get('contentFilter', {})
        contentFilter.update(kwargs.get('contentFilter', {}))
        kwargs.setdefault('custom_query', contentFilter)
        kwargs.setdefault('batch', True)
        kwargs.setdefault('b_size', self.b_size)
        kwargs.setdefault('b_start', self.b_start)
        default_values = kwargs.pop('default_values', {})

        if bool(getattr(self.context, 'show_filter', None)):
            return self.filtered_result(default_values=default_values,
                **kwargs)
        else:
            # fallback to default
            return self.collection_behavior.results(**kwargs)


class FilteredEventListing(CollectionFilter, EventListing):

    @memoize
    def events(self, ret_mode=RET_MODE_ACCESSORS, expand=True, batch=True):
        res = []
        if self.is_collection:
            ctx = self.default_context
            # Whatever sorting is defined, we're overriding it.
            sort_on = 'start'
            sort_order = None
            if self.mode in ('past', 'all'):
                sort_order = 'reverse'
            query = queryparser.parseFormquery(
                ctx, ctx.query, sort_on=sort_on, sort_order=sort_order)
            custom_query = self.request.get('contentFilter', {})
            if 'start' not in query or 'end' not in query:
                # ... else don't show the navigation bar
                start, end = self._start_end
                start, end = _prepare_range(ctx, start, end)
                custom_query.update(start_end_query(start, end))
            # BAM ... inject our filter viewlet values
            res = self.filtered_result(
                batch=False, brains=True, custom_query=custom_query)
            if expand:
                # get start and end values from the query to ensure limited
                # listing for occurrences
                start, end = self._expand_events_start_end(
                    query.get('start') or custom_query.get('start'),
                    query.get('end') or custom_query.get('end'))
                res = expand_events(
                    res, ret_mode,
                    start=start, end=end,
                    sort=sort_on, sort_reverse=True if sort_order else False)
        else:
            res = self._get_events(ret_mode, expand=expand)
        if batch:
            b_start = self.b_start
            b_size = self.b_size
            res = Batch(res, size=b_size, start=b_start, orphan=self.orphan)
        return res
