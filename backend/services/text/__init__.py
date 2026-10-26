"""services/text/__init__.py — package marker.

Hosts cross-router text-munging helpers.  Shipped alongside
Ticket JJ's ``html_to_plain``; expand as sibling helpers land.
"""
from .html_to_plain import html_to_plain

__all__ = ["html_to_plain"]
