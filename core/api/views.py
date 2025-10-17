from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from oauth2_provider.contrib.rest_framework import TokenHasScope

from core.models import PatientProfile
from .serializers import PatientSerializer
from .permissions import IsPhysician


class PatientListView(ListAPIView):
    """
    Lists patients linked to the authenticated physician.
    Requires OAuth2 token with `read` scope.
    """
    serializer_class = PatientSerializer
    permission_classes = [IsAuthenticated, TokenHasScope, IsPhysician]
    required_scopes = ["read"]

    def get_queryset(self):
        # Safely handle users without a physician profile
        doctor = getattr(self.request.user, "physician", None)
        if doctor is None:
            return PatientProfile.objects.none()
        return (
            PatientProfile.objects
            .filter(physician=doctor)
            .select_related("physician")
            .order_by("full_name")
        )


class PatientDetailView(RetrieveAPIView):
    """
    Fetch a single patient (by pk) that belongs to the authenticated physician.
    Requires OAuth2 token with `read` scope.
    """
    serializer_class = PatientSerializer
    permission_classes = [IsAuthenticated, TokenHasScope, IsPhysician]
    required_scopes = ["read"]
    lookup_field = "pk"

    def get_queryset(self):
        # Restrict to patients owned by the requesting physician
        doctor = getattr(self.request.user, "physician", None)
        if doctor is None:
            return PatientProfile.objects.none()
        return (
            PatientProfile.objects
            .filter(physician=doctor)
            .select_related("physician")
        )
