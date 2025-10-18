# core/api/views.py
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
    Fetch a single patient (by public UUID) belonging to the authenticated physician.
    Requires OAuth2 token with `read` scope.
    """
    serializer_class = PatientSerializer
    permission_classes = [IsAuthenticated, TokenHasScope, IsPhysician]
    required_scopes = ["read"]

    # 🔑 use the UUID field from the model and the <uuid:public_id> from the URL
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"

    # limit to patients of the authenticated physician
    queryset = PatientProfile.objects.select_related("physician")

