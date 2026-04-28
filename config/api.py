from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from ninja import NinjaAPI
from ninja.security import SessionAuth

from chattersift.core.extension_points import import_string

api = NinjaAPI(
    urls_namespace="api",
    auth=SessionAuth(),
    docs_decorator=staff_member_required,
)

for prefix, router_path in settings.CHATTERSIFT_API_ROUTERS:
    api.add_router(prefix, import_string(router_path))
