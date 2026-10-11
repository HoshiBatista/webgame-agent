import os

PARENT_CSP = (
    "frame-src "
    + os.environ.get("PROMPT2PLAY_PREVIEW_ORIGIN", "http://127.0.0.1:8001").rstrip("/")
    + "; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)


def static_headers(headers, path, url):
    # WhiteNoise is before Django views, so index.html needs the same parent policy.
    if path.lower().endswith(".html"):
        headers["Content-Security-Policy"] = PARENT_CSP
        headers["Cache-Control"] = "no-cache"
        headers["X-Frame-Options"] = "DENY"


class APIResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            response["Cache-Control"] = "no-store"
            response["X-Content-Type-Options"] = "nosniff"
        return response
