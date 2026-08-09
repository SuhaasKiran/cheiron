"""Minimal NumPy typing boundary used by pytest's optional type imports.

NumPy 2.5's bundled stubs require Python 3.12 syntax, while this project type
checks its declared Python 3.11 compatibility. The application does not use
NumPy directly, so its runtime package remains untouched.
"""

class ndarray: ...
