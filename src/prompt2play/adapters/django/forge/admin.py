from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Event, Job, Project, Runner, User, Version

admin.site.site_header = "Game Forge · команда"
admin.site.register(User, UserAdmin)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Version)
class VersionAdmin(ReadOnlyAdmin):
    list_display = ["id", "project", "number", "is_reference", "created_at"]
    list_filter = ["is_reference"]
    exclude = ["html", "files"]


@admin.register(Job)
class JobAdmin(ReadOnlyAdmin):
    list_display = ["id", "project", "status", "provider", "stage", "updated_at"]
    list_filter = ["status", "provider"]
    exclude = ["lease_hash", "checkpoint"]


@admin.register(Runner)
class RunnerAdmin(ReadOnlyAdmin):
    list_display = ["name", "last_seen", "revoked"]
    exclude = ["token_hash"]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["title", "created_at", "updated_at"]
    readonly_fields = ["id", "created_by", "latest_version", "created_at", "updated_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Event)
class EventAdmin(ReadOnlyAdmin):
    list_display = ["id", "job", "stage", "level", "created_at"]
