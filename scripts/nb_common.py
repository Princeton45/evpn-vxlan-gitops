import os
import pynetbox

NETBOX_URL   = os.environ.get("NETBOX_URL", "http://localhost:8000")
NETBOX_TOKEN = os.environ.get("NETBOX_TOKEN", "mqtQgzltkHA29cxarrlqAi1U9LvJKKcZhzV3wVxj")

def get_api():
    nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)
    nb.http_session.verify = False
    return nb

def slug(s):
    return s.lower().replace(" ", "-").replace("/", "-")

def get_or_create(endpoint, search, defaults=None):
    """Return existing object matching `search`, else create with search+defaults."""
    obj = endpoint.get(**search)
    if obj:
        return obj, False
    payload = dict(search)
    if defaults:
        payload.update(defaults)
    return endpoint.create(**payload), True
