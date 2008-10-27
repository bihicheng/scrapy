"""
This module provides a mechanism for collecting one (or more) sample items per
domain.

The items are collected in a dict of guid->item and persisted by pickling that
dict into a file.

This can be useful for testing changes made to the framework or other common
code that affects several spiders.

It uses the scrapy stats service to keep track of which domains are already
sampled.

Settings that affect this module:

ITEMSAMPLER_FILE
  file where to store the pickled dict of scraped items
"""

from __future__ import with_statement

import cPickle as pickle

from pydispatch import dispatcher

from scrapy.core.engine import scrapyengine
from scrapy.core.exceptions import NotConfigured, DropItem
from scrapy.core import signals
from scrapy.stats import stats
from scrapy import log
from scrapy.conf import settings

items_per_domain = settings.getint('ITEMSAMPLER_COUNT', 1)
close_domain = settings.getbool('ITEMSAMPLER_CLOSE_DOMAIN', False)

class ItemSamplerPipeline(object):

    def __init__(self):
        self.filename = settings['ITEMSAMPLER_FILE']
        if not self.filename:
            raise NotConfigured
        self.items = {}
        self.domains_count = 0
        self.empty_domains = set()
        dispatcher.connect(self.domain_closed, signal=signals.domain_closed)
        dispatcher.connect(self.engine_stopped, signal=signals.engine_stopped)

    def process_item(self, domain, response, item):
        sampled = stats.getpath("%s/items_sampled" % domain, 0)
        if sampled < items_per_domain:
            self.items[item.guid] = item
            sampled += 1
            stats.setpath("%s/items_sampled" % domain, sampled)
            if close_domain and sampled == items_per_domain:
                scrapyengine.close_domain(domain)
        return item

    def engine_stopped(self):
        with open(self.filename, 'w') as f:
            pickle.dump(self.items, f)
        if self.empty_domains:
            log.msg("Empty domains (no items scraped) found: %s" % " ".join(self.empty_domains), level=log.WARNING)

    def domain_closed(self, domain, spider, status):
        if status == 'finished' and not stats.getpath("%s/items_sampled" % domain):
            self.empty_domains.add(domain)
        self.domains_count += 1
        log.msg("Sampled %d domains so far (%d empty)" % (self.domains_count, len(self.empty_domains)), level=log.INFO)


class ItemSamplerMiddleware(object):
    """This middleware drops items and requests (when domain sampling has been
    completed) to accelerate the processing of remaining domains"""

    def __init__(self):
        if not settings['ITEMSAMPLER_FILE']:
            raise NotConfigured

    def process_scrape(self, response, spider):
        if stats.getpath("%s/items_sampled" % spider.domain_name) >= items_per_domain:
            return []

    def process_result(self, response, result, spider):
        if stats.getpath("%s/items_sampled" % spider.domain_name) >= items_per_domain:
            return []
        else:
            return result