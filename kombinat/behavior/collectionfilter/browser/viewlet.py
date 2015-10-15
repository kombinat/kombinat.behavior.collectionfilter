from Products.CMFPlone import PloneMessageFactory as _pmf
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from logging import getLogger
from operator import itemgetter
from plone import api
from plone.app.layout.viewlets import common
from plone.app.querystring import queryparser
from plone.app.vocabularies.types import PortalTypesVocabulary
from plone.dexterity.utils import safe_unicode
from zope.dottedname.resolve import resolve as resolve_dottedname
from zope.i18n import translate

from ..behavior import _

logger = getLogger(__name__)


FILTER_TRANSLATION_MAP = dict(
    Subject=_('-- all Subjects --'),
    path=_('-- all Locations --'),
    portal_type=_('-- all Types --'),
)

FILTER_VOCABULARY_MAP = dict(
    portal_type=PortalTypesVocabulary(),
)


class CollectionFilterViewlet(common.ViewletBase):
    index = ViewPageTemplateFile('collection_filter.pt')

    def available(self):
        return bool(getattr(self.context, 'show_filter', None))

    def filter_fields(self):
        fields = ()
        d_vals = getattr(self.view, 'default_values', {})
        p_query = queryparser.parseFormquery(self.context, self.context.query)
        try:
            trans_map = resolve_dottedname(api.portal.get_registry_record(
                'kombinat.behavior.collectionfilter.translation_map'))
        except:
            # fallback
            trans_map = FILTER_TRANSLATION_MAP or {}
        try:
            vocab_map = resolve_dottedname(api.portal.get_registry_record(
                'kombinat.behavior.collectionfilter.vocabulary_map'))
        except:
            # fallback
            vocab_map = FILTER_VOCABULARY_MAP or {}

        for idx in trans_map.keys():
            qvals = p_query.get(idx, {}).get('query', [])
            i_sel = safe_unicode(self.request.get(idx) or d_vals.get(idx))
            label_vocab = vocab_map.get(idx,
                lambda x: None)(self.context)

            def option_label(value):
                if label_vocab:
                    try:
                        return label_vocab.getTermByToken(value).title
                    except:
                        pass
                return translate(_pmf(value), context=self.request)

            if idx == 'path':
                vals = []
                for v in qvals:
                    try:
                        loc_title = self.context.restrictedTraverse(
                            v.encode('utf8')).Title()
                    except Exception, msg:
                        logger.info("error: {}".format(msg))
                        continue
                    vals.append(dict(value=v, title=loc_title,
                        selected=i_sel == v and 'selected' or ''))
            else:
                vals = [dict(value=v, title=option_label(v),
                    selected=safe_unicode(i_sel) == v \
                    and 'selected' or '') for v in qvals if v]
            if not vals or len(vals) < 2:
                continue
            fields += (dict(
                name=idx,
                placeholder=translate(trans_map.get(idx, idx),
                    context=self.request),
                options=sorted(vals, key=itemgetter('title')),
            ), )
        return fields
