"""Process package: contains all processing modules for the phone-stream server.

This package includes:
- process_ai: AI-powered text processing (Mistral Large 4)
- process_command: Handle user-typed commands
- process_domain: Domain-specific processing dispatcher
- process_informatique: IT/Computer Science domain processor
- process_interactive: Fast reaction to realtime transcription (menu commands)
- process_pastoral: Religious/spiritual domain processor
- process_text: Main text processing hook (integrates domain + AI)
- process_theologique: Theology domain processor
"""

from __future__ import annotations
