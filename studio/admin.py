from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Budget, Chat, Publication, User

admin.site.register(User, UserAdmin)
admin.site.register([Chat, Publication, Budget])
