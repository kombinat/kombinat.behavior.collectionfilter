from DateTime import DateTime
from Products.AdvancedQuery import Generic, Between
from logging import getLogger
from plone import api
from plone.app.contentlisting.interfaces import IContentListing
from plone.app.contenttypes.browser.collection import CollectionView
from plone.app.event.base import RET_MODE_ACCESSORS
from plone.app.event.base import _prepare_range
from plone.app.event.base import expand_events
from plone.app.event.base import start_end_query
from plone.app.event.browser.event_listing import EventListing
from plone.app.querystring import queryparser
from plone.batching import Batch
from plone.dexterity.utils import (
    safe_unicode,
    safe_utf8,
)
from plone.memoize.instance import memoizedproperty
from plone.memoize.view import memoize

import itertools

logger = getLogger(__name__)


class CollectionFilter(object):

    @memoizedproperty
    def default_values(self):
        dflt = self.context.default_filter_values
        if not dflt:
            return {}
        return dict([map(safe_unicode, l.split(":")) for l in dflt])

    def filtered_result(self, **kwargs):
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
        if 'default_values' in kwargs:
            fdata = kwargs.pop('default_values')
        else:
            fdata = self.default_values

        adv_q = None
        pquery = queryparser.parseFormquery(self.context, self.context.query)
        # setup default values and filter data
        fdata.update(self.request.form)
        # fix pickadate value
        if not fdata.get('_submit') is None:
            fdata['start'] = fdata['_submit']
            del fdata['_submit']
        _ignored_keys = ('path', 'portal_type', 'b_start', 'b_size',
            'ajax_load', 'start')
        _allow_none = self.context.allow_empty_values_for or []
        # AND concatenation for request values
        _subject_encode = lambda k, v: k == 'Subject' and safe_utf8(v) or \
            safe_unicode(v)
        AND_query = tuple([Generic(k, _subject_encode(k, v)) for k, v \
            in fdata.items() if v and k not in _ignored_keys])

        # XXX: there has to be a pythonic way to join a list
        # with operators ...
        for idx in AND_query:
            if not adv_q:
                adv_q = idx
                continue
            adv_q &= idx

        if not adv_q:
            for idx in ([Generic(k, v['query']) for k, v \
            in pquery.items() if k not in itertools.chain(
            _ignored_keys, _allow_none)]):
                if idx._idx == 'Subject':
                    idx._term = map (safe_utf8, idx._term)
                if not adv_q:
                    adv_q = idx
                    continue
                adv_q |= idx

        # special case for event listing filter
        if fdata.get('start'):
            st = DateTime("{} 00:00".format(fdata.get('start'))).asdatetime()
            se = DateTime("{} 23:59".format(fdata.get('start'))).asdatetime()
            adv_val = Between('start', st, se)
            if adv_q:
                adv_q &= adv_val
            else:
                adv_q = adv_val

        if fdata.get('portal_type') or pquery.get('portal_type'):
            adv_val = Generic('portal_type', fdata.get('portal_type') or \
                pquery.get('portal_type'))
            if adv_q:
                adv_q &= adv_val
            else:
                adv_q = adv_val

        # respect INavigationRoot or ILanguageRootFolder or ISubsite
        path_val = Generic('path', fdata.get('path') or pquery.get('path') or \
            '/'.join(api.portal.get_navigation_root(
            self.context).getPhysicalPath()))
        if adv_q:
            adv_q &= path_val
        else:
            adv_q = path_val

        sort_on = ((getattr(self.context, 'sort_on', 'sortable_title'),
            self.context.sort_reversed and 'desc' or 'asc'), )
        try:
            logger.info(adv_q)
            _res = self.context.portal_catalog.evalAdvancedQuery(adv_q,
                sort_on)
            listing = IContentListing(_res)
            if kwargs.get('batch', False):
                return Batch(listing, kwargs.get('b_size', 100),
                    start=kwargs.get('b_start', 0))
            return listing
        except Exception, msg:
            logger.info("Could not apply filtered search: {}, {}".format(
                msg, fdata))

        # fallback to default
        return self.collection_behavior.results(**kwargs)


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

        if bool(self.context.show_filter):
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
