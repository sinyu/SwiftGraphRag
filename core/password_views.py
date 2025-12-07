from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse_lazy
from django.contrib import messages

class CustomPasswordChangeView(PasswordChangeView):
    """
    Custom password change view that clears the password_change_required flag.
    """
    template_name = 'registration/password_change_form.html'
    success_url = reverse_lazy('password_change_done')
    
    def form_valid(self, form):
        response = super().form_valid(form)
        # Clear the password change required flag
        if hasattr(self.request.user, 'profile'):
            self.request.user.profile.password_change_required = False
            self.request.user.profile.save()
        return response
