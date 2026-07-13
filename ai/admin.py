from django.contrib import admin
from .models import AIModel

@admin.register(AIModel)
class AIAdmin(admin.ModelAdmin):
    list_filter = ["status"]
