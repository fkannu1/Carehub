from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.middleware.csrf import get_token

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from core.api.serializers import (
    UserBasicSerializer,
    PhysicianRegisterSerializer,
    PatientRegisterSerializer,
    PhysicianLookupSerializer,
)
from core.models import PhysicianProfile


@ensure_csrf_cookie
def csrf(request):
    """
    Sets/refreshes the 'csrftoken' cookie and also returns the token in JSON,
    so the frontend can immediately set the X-CSRFToken header (no race with cookies).
    """
    token = get_token(request)  # this also ensures middleware will set the cookie
    return JsonResponse({"csrfToken": token})


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        user = authenticate(request, username=username, password=password)
        if not user:
            return Response(
                {"detail": "Invalid credentials"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        login(request, user)

        # Provide a fresh CSRF token after login.
        token = get_token(request)
        data = {
            "user": UserBasicSerializer(user).data,
            "csrfToken": token,
        }
        return Response(data)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        token = get_token(request)
        data = {"detail": "logged out", "csrfToken": token}
        return Response(data)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"user": UserBasicSerializer(request.user).data})


# ----------------------------
# Registration & physician lookup
# ----------------------------
class PhysicianRegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        s = PhysicianRegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.save()
        return Response(data, status=status.HTTP_201_CREATED)


class PatientRegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        s = PatientRegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.save()
        return Response(data, status=status.HTTP_201_CREATED)


class PhysicianLookupByCodeView(APIView):
    """
    GET /api/physicians/lookup/?code=ABCD1234
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        code = (request.query_params.get("code") or "").strip().upper()
        if not code:
            return Response({"detail": "Missing ?code="}, status=400)
        p = PhysicianProfile.objects.filter(connect_code=code).first()
        if not p:
            return Response({"detail": "Not found"}, status=404)
        return Response(PhysicianLookupSerializer(p).data)