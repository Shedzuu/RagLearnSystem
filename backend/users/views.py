from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import User
from .serializers import RegisterSerializer, UserSerializer


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Accept 'email' in request body; map to username for auth (USERNAME_FIELD=email)."""

    def get_fields(self):
        fields = super().get_fields()
        # Let client send either email or username; we'll map email -> username in validate
        fields['email'] = serializers.EmailField(required=False, write_only=True)
        if 'username' in fields:
            fields['username'].required = False
        return fields

    def validate(self, attrs):
        # Parent expects attrs[USERNAME_FIELD] = attrs['email']; we accept 'email' or 'username' as input
        val = attrs.get('email') or attrs.get('username')
        if not val:
            raise serializers.ValidationError({'email': 'Email is required.'})
        attrs['email'] = val
        if 'username' in attrs:
            del attrs['username']
        return super().validate(attrs)


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (AllowAny,)
    serializer_class = RegisterSerializer

    def perform_create(self, serializer):
        user = serializer.save()
        return user


class UserMeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user
