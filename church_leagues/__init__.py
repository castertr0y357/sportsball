import sys

# Python 3.14+ compatibility patch for Django 5.x BaseContext.__copy__
if sys.version_info >= (3, 14):
    try:
        from django.template import context

        def _patched_copy(self):
            duplicate = self.__class__.__new__(self.__class__)
            duplicate.dicts = self.dicts[:]
            return duplicate

        context.BaseContext.__copy__ = _patched_copy
    except ImportError:
        pass
