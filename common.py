#!/usr/bin/python
# Copyright (C) 2012 Humbug, Inc.  All rights reserved.
import simplejson
import requests
import time
import traceback
import urlparse
import sys

# Check that we have a recent enough version
# Older versions don't provide the 'json' attribute on responses.
assert(requests.__version__ > '0.12')

class HumbugAPI():
    def __init__(self, email, api_key, verbose=False, retry_on_errors=True,
                 site="https://humbughq.com", client="API"):
        self.api_key = api_key
        self.email = email
        self.verbose = verbose
        self.base_url = site
        self.retry_on_errors = retry_on_errors
        self.client_name = client

    def do_api_query(self, request, url, longpolling = False):
        had_error_retry = False
        request["email"] = self.email
        request["api-key"] = self.api_key
        request["client"] = self.client_name

        for (key, val) in request.iteritems():
            if not (isinstance(val, str) or isinstance(val, unicode)):
                request[key] = simplejson.dumps(val)

        request["failures"] = 0

        while True:
            try:
                res = requests.post(urlparse.urljoin(self.base_url, url), data=request,
                                    verify=True, timeout=55)

                # On 50x errors, try again after a short sleep
                if str(res.status_code).startswith('5') and self.retry_on_errors:
                    if self.verbose:
                        if not had_error_retry:
                            sys.stdout.write("connection error %s -- retrying." % (res.status_code,))
                            had_error_retry = True
                            request["failures"] += 1
                        else:
                            sys.stdout.write(".")
                        sys.stdout.flush()
                    time.sleep(1)
                    continue
            except (requests.exceptions.Timeout, requests.exceptions.SSLError) as e:
                # Timeouts are either a Timeout or an SSLError; we
                # want the later exception handlers to deal with any
                # non-timeout other SSLErrors
                if (isinstance(e, requests.exceptions.SSLError) and
                    str(e) != "The read operation timed out"):
                    raise
                if longpolling:
                    # When longpolling, we expect the timeout to fire,
                    # and the correct response is to just retry
                    continue
                else:
                    return {'msg': "Connection error:\n%s" % traceback.format_exc(),
                            "result": "connection-error"}
            except requests.exceptions.ConnectionError:
                if self.retry_on_errors:
                    if self.verbose:
                        if not had_error_retry:
                            sys.stdout.write("connection error -- retrying.")
                            had_error_retry = True
                            request["failures"] += 1
                        else:
                            sys.stdout.write(".")
                        sys.stdout.flush()
                    time.sleep(1)
                    continue
                return {'msg': "Connection error:\n%s" % traceback.format_exc(),
                        "result": "connection-error"}
            except Exception:
                # We'll split this out into more cases as we encounter new bugs.
                return {'msg': "Unexpected error:\n%s" % traceback.format_exc(),
                        "result": "unexpected-error"}

            if self.verbose and had_error_retry:
                print "Success!"
            if res.json is not None:
                return res.json
            return {'msg': res.text, "result": "http-error",
                    "status_code": res.status_code}

    def send_message(self, request):
        return self.do_api_query(request, "/api/v1/send_message")

    def get_messages(self, request = {}):
        return self.do_api_query(request, "/api/v1/get_messages",
                                 longpolling=True)

    def get_profile(self, request = {}):
        return self.do_api_query(request, "/api/v1/get_profile")

    def get_public_streams(self, request = {}):
        return self.do_api_query(request, "/api/v1/get_public_streams")

    def list_subscriptions(self, request = {}):
        return self.do_api_query(request, "/api/v1/subscriptions/list")

    def add_subscriptions(self, streams):
        request = {'streams': streams}
        return self.do_api_query(request, "/api/v1/subscriptions/add")

    def call_on_each_message(self, callback, options = {}):
        max_message_id = None
        while True:
            if max_message_id is not None:
                options["first"] = "0"
                options["last"] = str(max_message_id)
            res = self.get_messages(options)
            if 'error' in res.get('result'):
                if self.verbose:
                    if res["result"] == "http-error":
                        print "HTTP error fetching messages -- probably a server restart"
                    elif res["result"] == "connection-error":
                        print "Connection error fetching messages -- probably server is temporarily down?"
                    else:
                        print "Server returned error:\n%s" % res["msg"]
                # TODO: Make this back off once it's more reliable
                time.sleep(1)
                continue
            for message in sorted(res['messages'], key=lambda x: int(x["id"])):
                max_message_id = max(max_message_id, int(message["id"]))
                callback(message)
