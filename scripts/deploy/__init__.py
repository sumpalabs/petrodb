"""Deploy-time helpers.

Modules here run in the deploy workflow (CI), not during dataset transform or
export. They take the already-built `parquet/` tree plus the doc surfaces and
prepare them for the two publish targets (Hugging Face + Cloudflare, ADR-0005).
"""
