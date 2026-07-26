from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth import authenticate
from .models import UserModel


class MyTokenSerializer(TokenObtainPairSerializer):
    username_field = 'email'
    default_error_messages = {
        "no_active_account": "Email or Password is wrong"
    }

    def validate(self, attrs):
        credentials = {
            "email": attrs.get("email"),
            "password": attrs.get("password")
        }

        user = authenticate(**credentials)

        if user is None:
            raise AuthenticationFailed("Email or Password is wrong")

        if not user.is_active:
            raise AuthenticationFailed("User inactive")

        if not user.is_email_verified:
            raise AuthenticationFailed('Email is not verified')

        data = super().get_token(user)

        return {
            "refresh": str(data),
            "access": str(data.access_token),
        }


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = UserModel
        read_only_fields = ['is_phone_verified', 'registration_date']
        exclude = ['groups', 'user_permissions']


class AuthTokenSerializer(serializers.Serializer):
    email = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)
    token = serializers.CharField(read_only=True)

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        if email and password:
            user = authenticate(request=self.context.get('request'),
                                username=email, password=password)

            if not user:
                msg = 'Unable to log in with provided credentials.'
                raise serializers.ValidationError(msg, code='authorization')
        else:
            msg = 'Must include "email" and "password".'
            raise serializers.ValidationError(msg, code='authorization')

        attrs['user'] = user
        return attrs


class EmailVerificationSerializer(serializers.Serializer):
    code = serializers.CharField()


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_new_password = serializers.CharField(write_only=True)


class ResetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True)
    confirm_new_password = serializers.CharField(write_only=True)
