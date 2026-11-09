#!/usr/bin/env python3
"""Fixture-client redirect guard. Not wired to the XDM Android downloader.

The real MP01/MP10 consumers must independently enforce the same credential
boundary; a passing test here is NOT production redirect containment evidence.
"""
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

SECRETS = {'authorization', 'cookie', 'proxy-authorization'}


def origin(url):
    p = urlsplit(url)
    port = p.port or (443 if p.scheme == 'https' else 80)
    return (p.scheme.lower(), (p.hostname or '').lower(), port)


class ScopedRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        previous = origin(req.full_url)
        new = origin(newurl)
        if new[0] not in ('http', 'https'):
            raise ValueError('unsupported redirect scheme')
        if previous[0] == 'https' and new[0] != 'https':
            raise ValueError('refusing HTTPS-to-HTTP downgrade')
        candidate = super().redirect_request(req, fp, code, msg, headers, newurl)
        if candidate is None:
            return None
        if new != previous:
            for bucket in (candidate.headers, candidate.unredirected_hdrs):
                for k in list(bucket):
                    if k.lower() in SECRETS:
                        del bucket[k]
        return candidate


def opener():
    return build_opener(ScopedRedirectHandler())
