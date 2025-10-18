# core/api/permissions.py
from rest_framework.permissions import BasePermission


class IsPhysician(BasePermission):
    """
    Allows access only to users who have a PhysicianProfile attached.
    Assumes a related_name 'physician' on the User -> PhysicianProfile relation.
    """

    message = "You must be a physician to access this resource."

    def has_permission(self, request, view):
        return bool(getattr(request.user, "is_authenticated", False) and hasattr(request.user, "physician"))
