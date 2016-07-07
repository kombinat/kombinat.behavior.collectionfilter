# -*- coding: utf-8 -*-
from DateTime import DateTime
from Products.AdvancedQuery import Between
from Products.AdvancedQuery import Generic
from kombinat.behavior.collectionfilter.interfaces import ICollectionFilter
from logging import getLogger
from plone.app.contentlisting.interfaces import IContentListing
from plone.app.contenttypes.browser.collection import CollectionView
from plone.app.contenttypes.interfaces import ICollection
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
from zope.component import adapter
from zope.interface import implementer
import itertools
import pkg_resources

try:
    pkg_resources.get_distribution('collective.solr')
except pkg_resources.DistributionNotFound:
    HAS_SOLR = False
    solrIsActive = lambda: False
else:
    from collective.solr.utils import isActive as solrIsActive
    HAS_SOLR = True

logger = getLogger(__name__)


class CollectionFilterAdvancedQuery(object):

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

    def exclude(self, val):
        if self.query is None:
            self.query = ~ val
        else:
            self.query = self.query & ~ val


@adapter(ICollection)
@implementer(ICollectionFilter)
class CollectionFilter(object):

    ignored_keys = (u'b_start', u'b_size', u'ajax_load', u'_authenticator',
        u'_filter_start', u'start', u'mode')
    force_AND = (u'path', u'portal_type')
    start_filter = '_filter_start'

    def __init__(self, context):
        self.context = context

    @property
    def default_values(self):
        dflt = self.context.default_filter_values
        if not dflt:
            return {}
        return dict([map(safe_unicode, l.split(":")) for l in dflt])

    @property
    def exclude_values(self):
        excl = self.context.exclude_filter_values or []
        excl_dict = {}
        for l in excl:
            k, v = l.split(":")
            v = self.safe_subject_encode(k, v)
            excl_dict[k] = "," in v and v.split(",") or v
        return excl_dict

    @property
    def parsed_query(self):
        return queryparser.parseFormquery(self.context, self.context.query,
            sort_on=getattr(self.context, 'sort_on', None))

    def filtered_result(self, **kwargs):
        if 'default_values' in kwargs:
            fdata = kwargs.pop('default_values')
        else:
            fdata = self.default_values

        pquery = kwargs.pop('pquery', self.parsed_query)

        # Subject Index has to be utf8 encoded
        if 'Subject' in pquery:
            subjects = pquery['Subject'].get('query', [])
            if not isinstance(subjects, list):
                subjects = list(subjects)
            pquery['Subject'] = dict(query=[safe_utf8(s) for s in subjects])

        try:
            return self.filtered_query(pquery, fdata,
                kwargs.get('batch', False), kwargs.get('b_size', 100),
                kwargs.get('b_start', 0))
        except Exception, msg:
            logger.info("Could not apply filtered search: %s, %s %s",
                msg, fdata, pquery)

    def filtered_query(self, pquery, fdata, batch, b_size, b_start):
        if HAS_SOLR and solrIsActive():
            result = self.solr_query(pquery, fdata)
        else:
            result = self.advanced_query(pquery, fdata)
        listing = IContentListing(result)
        if batch:
            return Batch(listing, b_size, start=b_start)
        return listing

    def advanced_query(self, pquery, fdata):
        sort_key = pquery.pop('sort_on', 'sortable_title')
        sort_on = (
            (sort_key, self.context.sort_reversed and 'reverse' or 'asc'),)
        q = self.advanced_query_builder(fdata, pquery=pquery)
        logger.info("AdvancedQuery: %s (sorting: %s", q, sort_on)
        return self.context.portal_catalog.evalAdvancedQuery(q, sort_on)

    def solr_query(self, pquery, fdata):
        sort_key = pquery.pop('sort_on', 'sortable_title')
        q = self.solr_query_builder(fdata, pquery)
        q.update({
            'sort_on': sort_key,
            'sort_order': self.context.sort_reversed and 'reverse' or 'asc',
        })
        logger.info("SOLR query: %s", q)
        return self.context.portal_catalog.searchResults(q)

    def OR_exclude(self):
        allow_none = self.context.allow_empty_values_for or []
        return list(itertools.chain(
            self.ignored_keys, self.force_AND, allow_none))

    def get_request_data(self):
        request = self.context.REQUEST
        req_allowed = set([x['i'] for x in self.context.query])
        # add special keys here
        req_allowed.add(self.start_filter)
        return dict([(k, v) for k, v in request.items() if k in req_allowed \
            and v])

    def safe_subject_encode(self, k, v):
        return k == 'Subject' and safe_utf8(v) or safe_unicode(v)

    def advanced_query_builder(self, fdata, pquery=None):
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
        _q = CollectionFilterAdvancedQuery()
        fdata.update(self.get_request_data())

        # OR concatenation of default fields
        for idx in ([Generic(k, v['query']) for k, v in pquery.items() \
        if k not in self.OR_exclude()]):
            if idx._idx == 'Subject':
                idx._term = map(safe_utf8, idx._term)
            _q |= idx

        # AND concatenation of request values
        for idx in ([Generic(k, self.safe_subject_encode(k, v)) for k, v \
        in fdata.items() if v and k not in self.ignored_keys]):
            _q &= idx

        # special case for event listing filter
        if fdata.get(self.start_filter):
            st = DateTime(fdata.get('_filter_start')).earliestTime()
            se = DateTime(fdata.get('_filter_start')).latestTime()
            _q &= Between('start', st, se)
        elif pquery.get('start'):
            _q &= Generic('start', pquery['start'])

        if fdata.get('portal_type') or pquery.get('portal_type'):
            _q &= Generic('portal_type', fdata.get('portal_type') or \
                pquery.get('portal_type'))

        # respect INavigationRoot or ILanguageRootFolder or ISubsite
        _q &= Generic('path', fdata.get('path') or pquery.get('path') or \
            getNavigationRoot(self.context))

        # add exclude values
        for name, value in self.exclude_values.items():
            _q.exclude(Generic(name, value))

        return _q.query

    def solr_query_builder(self, fdata, pquery):
        """ build query for solr search """
        fdata.update(self.get_request_data())
        query = dict([(k, self.safe_subject_encode(k, v)) for k, v \
            in fdata.items() if k not in self.ignored_keys])
        or_exclude = set(self.OR_exclude()).union(query.keys())
        or_q = dict([(k, v.get('query', v)) for k, v in pquery.items() \
            if k not in or_exclude])
        query.update(or_q)

        # special case for event listing filter
        if fdata.get(self.start_filter):
            st = DateTime(fdata[self.start_filter]).earliestTime()
            se = DateTime(fdata[self.start_filter]).latestTime()
            query.update({'start': {'query': [st, se], 'range': 'minmax'}})
        elif pquery.get('start'):
            query.update({'start': pquery['start']})

        # portal type
        if fdata.get('portal_type') or pquery.get('portal_type'):
            query.update({'portal_type': fdata.get('portal_type') or \
                pquery.get('portal_type')})

        # path
        query.update({'path': fdata.get('path') or pquery.get('path') or \
            getNavigationRoot(self.context)})

        return query


class FilteredCollectionView(CollectionView):

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
            fc_adapter = ICollectionFilter(self.context)
            filtered_result = fc_adapter.filtered_result(
                default_values=default_values, **kwargs)
            if filtered_result:
                return filtered_result

        # fallback to default
        return self.collection_behavior.results(**kwargs)


class FilteredEventListing(EventListing):

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
            fc_adapter = ICollectionFilter(ctx)
            res = fc_adapter.filtered_result(pquery=query, batch=False,
                custom_query=custom_query)
            if res is None:
                # ORIGINAL
                res = ctx.results(batch=False, brains=True,
                    custom_query=custom_query)
            if expand:
                # get start and end values from the query to ensure limited
                # listing for occurrences
                _filter_start = self.request.get('_filter_start')
                if _filter_start:
                    # check for pickadate day filtering
                    fs = DateTime(_filter_start).earliestTime()
                    fe = DateTime(_filter_start).latestTime()
                    start, end = self._expand_events_start_end(
                        dict(query=[fs, fe], range='minmax'), None)
                else:
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
