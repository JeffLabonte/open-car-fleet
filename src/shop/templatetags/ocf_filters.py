from django import template
from django.utils.formats import date_format

register = template.Library()


@register.filter
def ocf_datetime(value, arg="F j, Y, g:i a T"):
    if value is None:
        return ""
    try:
        return date_format(value, arg)
    except (AttributeError, ValueError):
        return str(value)


@register.filter
def ocf_date(value, arg="M j, Y"):
    if value is None:
        return ""
    try:
        return date_format(value, arg)
    except (AttributeError, ValueError):
        return str(value)
