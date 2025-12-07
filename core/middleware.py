from django.shortcuts import redirect
from django.urls import reverse

class ForcePasswordChangeMiddleware:
    """
    Middleware to force password change for users with password_change_required flag.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Check if user has profile and needs password change
            if hasattr(request.user, 'profile') and request.user.profile.password_change_required:
                # Allow access to password change, logout, and static files
                allowed_paths = [
                    reverse('password_change'),
                    reverse('password_change_done'),
                    reverse('logout'),
                ]
                
                if not any(request.path.startswith(path) for path in allowed_paths):
                    return redirect('password_change')
        
        response = self.get_response(request)
        return response
