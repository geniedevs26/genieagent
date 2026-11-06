"""GenieAgent core package.

Business lead discovery, email verification, AI qualification and owner-approved
outreach for Termux, GitHub Actions and n8n.

The package is intentionally dependency-free at runtime (Python standard library
only) so every script runs on Android/Termux without compiling native wheels.
"""

__version__ = "2.0.0"

SAFETY_BANNER = (
    "Automatic outreach is disabled by default. Nothing is sent without a "
    "per-message owner approval recorded in the tracking sheet."
)
