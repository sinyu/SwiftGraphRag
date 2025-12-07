from django.contrib import admin
from .models import KnowledgeSpace, Document, SpacePermission

admin.site.register(KnowledgeSpace)
admin.site.register(Document)
admin.site.register(SpacePermission)
