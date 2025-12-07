from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from .models import KnowledgeSpace, Document, User
from django.http import JsonResponse
from django.conf import settings
from django.contrib import messages
import os
import uuid

# RAG Imports
from rag_engine.store import DuckDBStore
from rag_engine.loader import DocumentIngestor
from rag_engine.graph import GraphRAG
from django.http import FileResponse, Http404

# Initialize Store (Global or Singleton pattern recommended for prod)
import sys
if 'test' in sys.argv:
    DB_PATH = ":memory:"
else:
    DB_PATH = os.path.join(settings.BASE_DIR, 'rag_data.duckdb')

store = DuckDBStore(db_path=DB_PATH)
ingestor = DocumentIngestor(store)
# Pass the embedding model from ingestor to GraphRAG for real query embeddings
rag = GraphRAG(store, embedding_model=ingestor.embeddings)

# Permission Helpers
def is_space_owner(user, space):
    if not user.is_authenticated:
        return False
    return space.owner == user or space.permissions.filter(user=user, role='owner').exists()

def is_space_member(user, space):
    if not user.is_authenticated:
        return False
    # Owners are also members
    if is_space_owner(user, space):
        return True
    return space.permissions.filter(user=user).exists()

from django.db.models import Q

def marketplace(request):
    """
    Public view showing all public spaces.
    If logged in, also shows private spaces the user has access to.
    Supports search via 'q' GET parameter.
    """
    query = request.GET.get('q', '')
    
    if request.user.is_authenticated:
        # Show public spaces OR spaces owned by user OR spaces where user is a member
        spaces = KnowledgeSpace.objects.filter(
            Q(is_public=True) | 
            Q(owner=request.user) | 
            Q(permissions__user=request.user)
        ).distinct()
    else:
        spaces = KnowledgeSpace.objects.filter(is_public=True)
        
    if query:
        spaces = spaces.filter(
            Q(name__icontains=query) |
            Q(description__icontains=query)
        )
        
    return render(request, 'marketplace.html', {'spaces': spaces, 'query': query})

@login_required
def dashboard(request):
    """
    Private view showing user's owned spaces and permitted spaces.
    """
    owned_spaces = request.user.owned_spaces.all()
    # permitted_spaces should be spaces where user has permission BUT is not the owner
    # AND the space is private (since public spaces are in marketplace)
    permitted_spaces = [
        p.space for p in request.user.space_permissions.select_related('space').filter(
            ~Q(space__owner=request.user) & Q(space__is_public=False)
        )
    ]
    return render(request, 'dashboard.html', {
        'owned_spaces': owned_spaces,
        'permitted_spaces': permitted_spaces
    })

@login_required
def admin_dashboard(request):
    """
    Superuser and Staff dashboard to manage spaces and users.
    """
    if not (request.user.is_superuser or request.user.is_staff):
        return render(request, '403.html', status=403)
    
    spaces = KnowledgeSpace.objects.all().order_by('-created_at')
    
    # Filter users based on permissions
    if request.user.is_superuser:
        users = User.objects.all().order_by('-date_joined')
    else:
        # Creators can only see Standard and Creator users, not Admins
        users = User.objects.filter(is_superuser=False).order_by('-date_joined')
    
    # Determine available roles for creating users
    if request.user.is_superuser:
        available_roles = [('user', 'Standard User'), ('creator', 'Knowledge Base Creator'), ('admin', 'Platform Admin')]
    else:
        available_roles = [('user', 'Standard User'), ('creator', 'Knowledge Base Creator')]
    
    return render(request, 'admin_dashboard.html', {
        'spaces': spaces,
        'users': users,
        'available_roles': available_roles
    })

@login_required
def create_user(request):
    """
    Admin view to create new users.
    Accessible by Superuser and Staff.
    """
    if not (request.user.is_superuser or request.user.is_staff):
        return render(request, '403.html', status=403)
        
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        role = request.POST.get('role')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists")
            return render(request, 'user_form.html')
            
        try:
            user = User.objects.create_user(username=username, email=email, password=password)
            if role == 'admin':
                # Only Superusers can create Admins
                if not request.user.is_superuser:
                    messages.error(request, "Only Superusers can create Admin users.")
                    return render(request, 'user_form.html')
                user.is_superuser = True
                user.is_staff = True
                user.save()
            elif role == 'creator':
                user.is_superuser = False
                user.is_staff = True
                user.save()
            
            # Create profile and set password change required
            from .models import UserProfile
            UserProfile.objects.create(user=user, password_change_required=True)
            
            messages.success(request, f"User {username} created successfully")
            return redirect('admin_dashboard')
        except Exception as e:
            messages.error(request, f"Error creating user: {e}")
            
    return render(request, 'user_form.html')

@login_required
def edit_user(request, user_id):
    """
    Admin view to edit user details and roles.
    Accessible by Superuser and Staff.
    """
    if not (request.user.is_superuser or request.user.is_staff):
        return render(request, '403.html', status=403)
        
    target_user = get_object_or_404(User, id=user_id)
    
    # Prevent Staff (Creator) from editing Superusers
    if target_user.is_superuser and not request.user.is_superuser:
        messages.error(request, "You do not have permission to edit Admin users.")
        return redirect('admin_dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        role = request.POST.get('role')
        
        # Check username uniqueness if changed
        if username != target_user.username and User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists")
            return render(request, 'user_edit_form.html', {'target_user': target_user})
            
        try:
            target_user.username = username
            target_user.email = email
            
            if role == 'admin':
                # Only Superusers can promote to Admin
                if not request.user.is_superuser:
                    messages.error(request, "Only Superusers can promote users to Admin.")
                    return render(request, 'user_edit_form.html', {'target_user': target_user})
                target_user.is_superuser = True
                target_user.is_staff = True
            elif role == 'creator':
                target_user.is_superuser = False
                target_user.is_staff = True
            else:
                # Prevent self-demotion if it leaves no admins (optional check, but good practice)
                if target_user == request.user:
                     messages.warning(request, "You cannot demote yourself while logged in.")
                else:
                    target_user.is_superuser = False
                    target_user.is_staff = False
            
            target_user.save()
            messages.success(request, f"User {username} updated successfully")
            return redirect('admin_dashboard')
        except Exception as e:
            messages.error(request, f"Error updating user: {e}")
            
    return render(request, 'user_edit_form.html', {'target_user': target_user})

@login_required
def delete_user(request, user_id):
    """
    Admin view to delete a user.
    Accessible by Superuser and Staff.
    """
    if not (request.user.is_superuser or request.user.is_staff):
        return render(request, '403.html', status=403)
        
    if request.method == 'POST':
        target_user = get_object_or_404(User, id=user_id)
        
        # Prevent Staff (Creator) from deleting Superusers
        if target_user.is_superuser and not request.user.is_superuser:
            messages.error(request, "You do not have permission to delete Admin users.")
            return redirect('admin_dashboard')
        
        if target_user == request.user:
            messages.error(request, "You cannot delete your own account.")
            return redirect('edit_user', user_id=user_id)
            
        username = target_user.username
        target_user.delete()
        messages.success(request, f"User {username} deleted successfully")
        
    return redirect('admin_dashboard')

@login_required
def manage_users(request, space_id):
    """
    View for space owners to manage members and roles.
    """
    space = get_object_or_404(KnowledgeSpace, id=space_id)
    
    if not is_space_owner(request.user, space):
        return render(request, '403.html', status=403)
        
    if request.method == 'POST':
        action = request.POST.get('action')
        username = request.POST.get('username')
        role = request.POST.get('role', 'member')
        
        try:
            target_user = User.objects.get(username=username)
            
            if action == 'add':
                # Don't add if already exists
                if not space.permissions.filter(user=target_user).exists() and target_user != space.owner:
                    # Role hierarchy check: User cannot assign a role higher than their own
                    # Currently, only owners can manage users, so this is implicitly safe for now as owners are top level.
                    # But if we allow members to manage, we need to check.
                    # For now, we just implement the requested logic: "can't add role that higher responsibility than its role"
                    
                    # Determine current user's role
                    current_user_role = 'member'
                    if space.owner == request.user:
                        current_user_role = 'owner'
                    else:
                        perm = space.permissions.filter(user=request.user).first()
                        if perm:
                            current_user_role = perm.role
                            
                    # Simple hierarchy: owner > member
                    if current_user_role == 'member' and role == 'owner':
                         messages.error(request, "You cannot assign a role higher than your own.")
                    elif role == 'owner' and not (target_user.is_staff or target_user.is_superuser):
                        # Enterprise Rule: Normal users cannot be owners
                        messages.error(request, "Standard users cannot be assigned as Space Owners.")
                    else:
                        from .models import SpacePermission
                        SpacePermission.objects.create(space=space, user=target_user, role=role)
                        messages.success(request, f"Added {username} as {role}")
                else:
                    messages.warning(request, f"{username} is already a member")
                    
            elif action == 'remove':
                if target_user == space.owner:
                    # Check if there is another owner
                    other_owners = space.permissions.filter(role='owner').exclude(user=target_user)
                    if other_owners.exists():
                        # Transfer ownership to the first available other owner
                        new_owner = other_owners.first().user
                        space.owner = new_owner
                        space.save()
                        # Remove the old owner's permission
                        space.permissions.filter(user=target_user).delete()
                        messages.success(request, f"Transferred ownership to {new_owner.username} and removed {username}")
                    else:
                        messages.error(request, "Cannot remove the only owner. Assign another owner first.")
                else:
                    space.permissions.filter(user=target_user).delete()
                    messages.success(request, f"Removed {username}")
                    
            elif action == 'update_role':
                if target_user == space.owner:
                    messages.error(request, "Cannot change role of primary owner")
                else:
                    perm = space.permissions.get(user=target_user)
                    perm.role = role
                    perm.save()
                    messages.success(request, f"Updated {username} to {role}")
                    
        except User.DoesNotExist:
            messages.error(request, "User not found")
        except Exception as e:
            messages.error(request, f"Error: {e}")
            
        return redirect('manage_users', space_id=space.id)

    permissions = space.permissions.select_related('user').all()
    # Get all users for autosuggest, excluding current members and owner
    existing_ids = [p.user.id for p in permissions] + [space.owner.id]
    all_users = User.objects.exclude(id__in=existing_ids).values('username')
    
    return render(request, 'manage_users.html', {'space': space, 'permissions': permissions, 'all_users': all_users})

def space_view(request, space_id):
    """
    Chat interface for a specific space.
    Checks permissions.
    """
    space = get_object_or_404(KnowledgeSpace, id=space_id)
    
    # Permission check
    if not space.is_public:
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
            
        if not is_space_member(request.user, space):
             return render(request, '403.html', status=403)

    is_owner = is_space_owner(request.user, space) if request.user.is_authenticated else False
    return render(request, 'space_view.html', {'space': space, 'is_owner': is_owner})

@login_required
def create_space(request):
    # Restrict space creation to Staff (Creators) and Superusers (Admins)
    if not (request.user.is_staff or request.user.is_superuser):
        return render(request, '403.html', status=403)

    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description')
        is_public = request.POST.get('is_public') == 'on'
        
        # Check for duplicate name
        if KnowledgeSpace.objects.filter(name=name).exists():
            messages.error(request, f"Space with name '{name}' already exists.")
            return render(request, 'space_form.html')

        space = KnowledgeSpace.objects.create(
            name=name,
            description=description,
            is_public=is_public,
            owner=request.user
        )
        
        # Add creator as owner in permissions too (for consistency)
        from .models import SpacePermission
        SpacePermission.objects.create(space=space, user=request.user, role='owner')
        
        return redirect('dashboard')
        return redirect('dashboard')
    return render(request, 'space_form.html')

@login_required
def edit_space(request, space_id):
    """
    View to edit space details.
    Accessible by Owner and Superuser.
    """
    space = get_object_or_404(KnowledgeSpace, id=space_id)
    
    # Permission check: Owner or Superuser
    if not (is_space_owner(request.user, space) or request.user.is_superuser):
        return render(request, '403.html', status=403)
        
    if request.method == 'POST':
        space.name = request.POST.get('name')
        space.description = request.POST.get('description')
        space.is_public = request.POST.get('is_public') == 'on'
        space.save()
        
        messages.success(request, f"Space '{space.name}' updated successfully")
        return redirect('space_view', space_id=space.id)
        
    return render(request, 'space_edit_form.html', {'space': space})

@login_required
def delete_space(request, space_id):
    """
    View to delete a space.
    Accessible by Owner and Superuser.
    """
    space = get_object_or_404(KnowledgeSpace, id=space_id)
    
    # Permission check: Owner or Superuser
    if not (is_space_owner(request.user, space) or request.user.is_superuser):
        return render(request, '403.html', status=403)
        
    if request.method == 'POST':
        name = space.name
        
        # Delete all documents and their files first
        for doc in space.documents.all():
            # Delete physical file
            if doc.file:
                try:
                    if os.path.exists(doc.file.path):
                        os.remove(doc.file.path)
                        print(f"Deleted file: {doc.file.path}")
                except Exception as e:
                    print(f"Error deleting file {doc.file.path}: {e}")
            
            # Delete from DuckDB
            try:
                store.delete_document(str(space_id), str(doc.id))
            except Exception as e:
                print(f"Error deleting document {doc.id} from store: {e}")
        
        # Delete the entire space from DuckDB
        try:
            store.delete_space(str(space_id))
        except Exception as e:
            print(f"Error deleting space from store: {e}")
        
        # Delete the Django space (cascades to documents)
        space.delete()
        messages.success(request, f"Space '{name}' and all associated data deleted successfully")
        
        if request.user.is_superuser and 'admin_dashboard' in request.META.get('HTTP_REFERER', ''):
            return redirect('admin_dashboard')
        return redirect('dashboard')
        
    return redirect('space_view', space_id=space.id)

@login_required
def upload_document(request, space_id):
    space = get_object_or_404(KnowledgeSpace, id=space_id)
    if not is_space_owner(request.user, space):
        return render(request, '403.html', status=403)
        
    if request.method == 'POST':
        files = request.FILES.getlist('files')
        
        if len(files) > 10:
            messages.error(request, "Maximum 10 files allowed at once")
            return redirect('space_view', space_id=space.id)
            
        for f in files:
            # Handle duplicate filenames by auto-versioning the title
            base_title = f.name
            title = base_title
            counter = 1
            
            # Check if a document with this title already exists in this space
            while Document.objects.filter(space=space, title=title).exists():
                # Extract name and extension
                name_parts = base_title.rsplit('.', 1)
                if len(name_parts) == 2:
                    name, ext = name_parts
                    title = f"{name} ({counter}).{ext}"
                else:
                    title = f"{base_title} ({counter})"
                counter += 1
            
            doc = Document.objects.create(space=space, title=title, file=f)
            # Ingest immediately (should be async task in prod)
            try:
                # Create temp file for ingestion since we need a path
                temp_path = os.path.join(settings.BASE_DIR, f"temp_{f.name}")
                with open(temp_path, 'wb+') as destination:
                    for chunk in f.chunks():
                        destination.write(chunk)
                
                # Ingest and get full text
                full_text = ingestor.ingest(temp_path, str(space.id), source_name=str(doc.id))
                
                # Generate Summary
                from rag_engine.summarization import generate_summary
                if full_text:
                    try:
                        summary = generate_summary(full_text)
                        doc.summary = summary
                    except Exception as e:
                        print(f"Summarization failed: {e}")
                
                os.remove(temp_path)
                doc.processed = True
                doc.save()
                messages.success(request, f"Successfully uploaded and ingested: {f.name}")
            except Exception as e:
                print(f"Error ingesting {doc.title}: {e}")
                messages.error(request, f"Error ingesting {f.name}: {e}")
                
        return redirect('space_view', space_id=space.id)
    return redirect('space_view', space_id=space.id)

@login_required
def delete_document(request, space_id, doc_id):
    """
    Delete a document and all its associated RAG data.
    """
    space = get_object_or_404(KnowledgeSpace, id=space_id)
    if not is_space_owner(request.user, space):
        return render(request, '403.html', status=403)

    doc = get_object_or_404(Document, id=doc_id, space=space)
    
    # Delete from DuckDB first (use ID for accurate lookup)
    try:
        store.delete_document(str(space_id), str(doc.id))
        messages.success(request, f"Successfully deleted '{doc.title}' and all associated data")
    except Exception as e:
        messages.error(request, f"Error deleting graph data: {e}")
    
    # Delete the physical file
    if doc.file:
        try:
            if os.path.exists(doc.file.path):
                os.remove(doc.file.path)
                print(f"Deleted file: {doc.file.path}")
        except Exception as e:
            print(f"Error deleting file {doc.file.path}: {e}")

    # Delete the Django record
    doc.delete()
    
    return redirect('space_view', space_id=space.id)

@login_required
def ingest_url_view(request, space_id):
    space = get_object_or_404(KnowledgeSpace, id=space_id)
    if not is_space_owner(request.user, space):
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)

    if request.method == 'POST':
        urls_text = request.POST.get('urls', '')
        # Split by newlines and filter empty strings
        urls = [u.strip() for u in urls_text.split('\n') if u.strip()]
        
        if not urls:
             messages.error(request, "No URLs provided")
             return redirect('space_view', space_id=space.id)
             
        if len(urls) > 10:
            messages.error(request, "Maximum 10 URLs allowed at once")
            return redirect('space_view', space_id=space.id)

        success_count = 0
        errors = []
        
        for url in urls:
            try:
                # Handle duplicate URLs by auto-versioning the title
                base_title = url
                title = base_title
                counter = 1
                
                # Check if a document with this title already exists in this space
                while Document.objects.filter(space=space, title=title).exists():
                    title = f"{base_title} ({counter})"
                    counter += 1
                
                # Create a Document record for the URL
                doc = Document.objects.create(space=space, title=title, file=None) # file is null for URL
                full_text = ingestor.ingest_url(url, str(space.id))
                
                # Generate Summary
                from rag_engine.summarization import generate_summary
                if full_text:
                    try:
                        summary = generate_summary(full_text)
                        doc.summary = summary
                    except Exception as e:
                        print(f"Summarization failed: {e}")
                        
                doc.processed = True
                doc.save()
                success_count += 1
            except Exception as e:
                errors.append(f"{url}: {str(e)}")
        
        if success_count > 0:
            messages.success(request, f"Successfully fetched {success_count} URLs")
        
        if errors:
            for err in errors:
                messages.error(request, f"Error fetching {err}")
                
        return redirect('space_view', space_id=space.id)
    return redirect('space_view', space_id=space.id)

def chat_api(request, space_id):
    """
    API endpoint for chat interactions (HTMX/Fetch).
    """
    space = get_object_or_404(KnowledgeSpace, id=space_id)
    if not space.is_public:
        if not is_space_member(request.user, space):
            return JsonResponse({'error': 'Permission denied'}, status=403)

    if request.method == 'POST':
        message = request.POST.get('message')
        document_id = request.POST.get('document_id')
        
        # Validate message is not empty
        if not message or not message.strip():
            return JsonResponse({'error': 'Message cannot be empty'}, status=400)
        
        # Run RAG Pipeline
        result = rag.run(message.strip(), str(space_id), target_doc=document_id)
        
        answer_generator = result.get('answer')
        citations = result.get('citations', [])
        
        # Format citations HTML
        citation_html = ""
        if citations:
            citation_html = '<div class="mt-2 text-xs text-gray-400 border-t border-gray-600 pt-2"><strong>Sources:</strong><ul class="list-disc pl-4">'
            for c in citations:
                source_name = c.get("source", "Unknown")
                clean_name = source_name.replace("temp_", "")
                # Check if source is a URL or file
                if clean_name.startswith("http"):
                     citation_html += f'<li><a href="{clean_name}" target="_blank" class="text-blue-400 hover:underline">{clean_name}</a></li>'
                else:
                    # Try to find by ID first (new behavior) - but validate it's a UUID first
                    doc = None
                    try:
                        import uuid
                        # Try to parse as UUID - if it works, it's an ID
                        uuid.UUID(clean_name)
                        doc = Document.objects.filter(id=clean_name).first()
                    except (ValueError, AttributeError):
                        # Not a valid UUID, treat as title (legacy behavior)
                        doc = Document.objects.filter(space__id=space_id, title=clean_name).first()
                        
                    if doc and doc.file:
                        citation_html += f'<li><a href="{doc.file.url}" target="_blank" class="text-blue-400 hover:underline">{doc.title}</a></li>'
                    else:
                        citation_html += f'<li>{clean_name}</li>'
            citation_html += '</ul></div>'

        from django.http import StreamingHttpResponse
        
        def stream_response():
            # Yield chunks from LLM
            if hasattr(answer_generator, '__iter__') and not isinstance(answer_generator, str):
                for chunk in answer_generator:
                    if hasattr(chunk, 'content'):
                        yield chunk.content
                    else:
                        yield str(chunk)
            else:
                yield str(answer_generator)
            
            # Yield citations at the end
            if citation_html:
                yield citation_html

        return StreamingHttpResponse(stream_response(), content_type='text/html')

    return JsonResponse({'error': 'Invalid request'}, status=400)

def serve_protected_media(request, path):
    """
    Serve media files with permission checks.
    Allows public access for public spaces.
    """
    from pathlib import Path
    # Construct full path
    document_root = Path(settings.MEDIA_ROOT) / 'documents'
    file_path = document_root / path
    
    # Check if file exists
    if not file_path.exists():
        raise Http404("Document not found")
        
    # Find the document object to check permissions
    try:
        # Try new format first: documents/space_{id}/filename.ext
        # Then try old format: documents/filename.ext
        db_path_new = f"documents/{path}"
        doc = Document.objects.filter(file=db_path_new).first()
        
        # If not found with new path, try old format (for legacy files)
        if not doc and '/' in path:
            # Extract just the filename from space_xxx/filename
            filename = path.split('/')[-1]
            db_path_old = f"documents/{filename}"
            doc = Document.objects.filter(file=db_path_old).first()
        
        if doc:
            space = doc.space
            # Check permissions
            if not space.is_public:
                if not request.user.is_authenticated:
                    from django.contrib.auth.views import redirect_to_login
                    return redirect_to_login(request.get_full_path())
                    
                if not is_space_member(request.user, space):
                    return render(request, '403.html', status=403)
        else:
            # If not found in DB but exists on disk, default to private/secure
            # Only superusers can access orphaned files
            if not request.user.is_authenticated:
                 from django.contrib.auth.views import redirect_to_login
                 return redirect_to_login(request.get_full_path())
                 
            if not request.user.is_superuser:
                 return render(request, '403.html', status=403)

        return FileResponse(open(file_path, 'rb'))
        
    except Exception as e:
        raise Http404("Error serving document")
