from django import template

register = template.Library()


@register.filter
def dict_get(mapping, key):
    """Look up a value in a dict using a variable key, returning 0 / None on miss."""

    if not mapping:
        return 0
    return mapping.get(key, 0)
