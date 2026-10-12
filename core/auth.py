from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password", "is_staff", "is_active"]
        read_only_fields = ["id"]

    def validate(self, attrs):
        if "password" in attrs:
            candidate = User(
                username=attrs.get("username", getattr(self.instance, "username", "")),
                email=attrs.get("email", getattr(self.instance, "email", "")),
            )
            validate_password(attrs["password"], candidate)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        return User.objects.create_user(**validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        instance = super().update(instance, validated_data)
        if password:
            instance.set_password(password)
            instance.save(update_fields=["password"])
        if password or not instance.is_active:
            Token.objects.filter(user=instance).delete()
        return instance


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.order_by("id")
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField()


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def get_authenticate_header(self, request):
        return "Token"

    @extend_schema(request=LoginSerializer, responses={200: TokenSerializer})
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request=request, **serializer.validated_data)
        if user is None:
            raise AuthenticationFailed("Invalid username or password.")
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key})


class LogoutView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        request.auth.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
