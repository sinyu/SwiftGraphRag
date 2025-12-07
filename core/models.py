from django.contrib.auth.models import User
from django.db import models
import uuid

def document_upload_path(instance, filename):
    """
    Upload files to space-specific directories.
    Format: documents/space_{space_id}/{filename}
    """
    return f'documents/space_{instance.space.id}/{filename}'

class UserProfile(models.Model):
    """
    Extension of Django User model for additional fields.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    password_change_required = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.user.username} Profile"


class KnowledgeSpace(models.Model):
    """
    A Knowledge Space is a collection of documents and a graph.
    It can be Public (visible to all) or Private (visible to owner/permitted users).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(default=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_spaces')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class Document(models.Model):
    """
    A document uploaded to a Knowledge Space.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    space = models.ForeignKey(KnowledgeSpace, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to=document_upload_path, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False) # True if ingested into RAG
    summary = models.TextField(blank=True, null=True) # AI-generated summary

    def __str__(self):
        return self.title

class SpacePermission(models.Model):
    """
    Explicit permissions for users to access private spaces.
    """
    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('member', 'Member'),
    ]
    space = models.ForeignKey(KnowledgeSpace, on_delete=models.CASCADE, related_name='permissions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='space_permissions')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')

    class Meta:
        unique_together = ('space', 'user')
