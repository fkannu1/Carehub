from rest_framework.permissions import BasePermission

class IsPhysician(BasePermission):
    """
    Allow only authenticated users whose role is PHYSICIAN.
    Works with your custom User that has is_physician().
    """
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "is_physician", lambda: False)()
        )
