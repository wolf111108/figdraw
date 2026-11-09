"""Scientific figures from explicit, versioned specifications."""

from figdraw.api import json_schema, load_spec, render, render_file, validate
from figdraw.errors import FigdrawError

__version__ = "0.1.0"
__all__ = ["FigdrawError", "json_schema", "load_spec", "render", "render_file", "validate"]
