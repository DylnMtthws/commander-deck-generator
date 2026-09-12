"""Packaged configuration YAML files.

Canonical YAML lives in the repository ``config/`` directory. This package
directory holds the same files (via links or copies) so an installed wheel
resolves them with :func:`sabermetrics.config.config_path` regardless of cwd.
"""
