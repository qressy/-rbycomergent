from django.conf import settings


def allauth_settings(request):
    """Expose some settings from django-allauth in templates."""
    return {
        "ACCOUNT_ALLOW_REGISTRATION": settings.ACCOUNT_ALLOW_REGISTRATION,
    }


def dashboard_chrome(request):
    """Expose dashboard shell extension templates to every template render."""
    return {
        "dashboard_account_menu_extension_template": settings.CHATTERSIFT_DASHBOARD_ACCOUNT_MENU_EXTENSION_TEMPLATE,
    }
