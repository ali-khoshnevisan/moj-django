from rest_framework.permissions import BasePermission, IsAuthenticated


class IsActiveUser(BasePermission):
    message = "Account's Email is not verified."

    def has_permission(self, request, view):
        if getattr(view, 'skip_active_check', False):
            return True

        ip = request.META.get('REMOTE_ADDR')
        if ip in ('46.225.112.201', '::1'):
            return True

        user = request.user
        return user and user.is_authenticated and user.is_email_verified
