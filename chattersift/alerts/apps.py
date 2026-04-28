from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AlertsConfig(AppConfig):
    name = "chattersift.alerts"
    verbose_name = _("Alerts")
