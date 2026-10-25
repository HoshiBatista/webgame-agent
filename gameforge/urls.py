from django.conf import settings
from django.contrib import admin
from django.urls import path, re_path
from django.views.static import serve

from studio import views as v

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", v.health_view),
    path("api/session/", v.session_view),
    path("api/login/", v.login_view),
    path("api/logout/", v.logout_view),
    path("api/chats/", v.chats_view),
    path("api/chats/<uuid:ident>/", v.chat_view),
    path("api/chats/<uuid:ident>/runs/", v.runs_view),
    path("api/chats/<uuid:ident>/restore/", v.restore_view),
    path("api/chats/<uuid:ident>/feedback/", v.feedback_view),
    path("api/runs/<uuid:ident>/", v.run_view),
    path("api/runs/<uuid:ident>/cancel/", v.cancel_view),
    path("api/runs/<uuid:ident>/continue/", v.continue_view),
    path("api/runs/<uuid:ident>/confirm/", v.confirm_view),
    path("api/runs/<uuid:ident>/recheck/", v.recheck_view),
    path("api/runs/<uuid:ident>/events/", v.events_view),
    path("api/runs/<uuid:ident>/diagnostics/", v.diagnostics_view),
    path("api/revisions/<uuid:ident>/", v.revision_view),
    path("api/revisions/<uuid:ident>/source/", v.source_view),
    path("api/revisions/<uuid:ident>/export/", v.export_view),
    path("api/revisions/<uuid:ident>/preview/", v.preview_link_view),
    path("api/publications/", v.publications_view),
    path("api/publications/<uuid:ident>/", v.publication_view),
    path("api/publications/<uuid:ident>/thumbnail/", v.publication_thumbnail_view),
    path("api/publications/<uuid:ident>/like/", v.like_view),
    path("api/publications/<uuid:ident>/remix/", v.remix_view),
    path("api/preferences/", v.preferences_view),
    path("preview/<str:token>/", v.preview_view),
    re_path(
        r"^assets/(?P<path>.*)$", serve, {"document_root": settings.BASE_DIR / "web" / "dist" / "assets"}
    ),
    re_path(r"^(?P<path>(?!api/).*)$", v.index_view),
]
