"""The loader registry. Adding a source is adding a file, not editing a command."""
LOADERS = {}


def register(cls):
    """Class decorator: put a Loader subclass into the registry under its dataset."""
    LOADERS[cls.dataset] = cls
    return cls


# Importing the modules is what populates LOADERS. Kept at the bottom because each
# module imports `register` from this one.
from external_data.loaders import seasonal  # noqa: E402,F401
