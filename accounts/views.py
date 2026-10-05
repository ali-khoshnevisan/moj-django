from rest_framework.views import APIView, status as http_status
from rest_framework.response import Response
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import OTPCodeModel, UserModel, ResetPasswordTokenModel
from .serializers import UserSerializer, AuthTokenSerializer, EmailVerificationSerializer, ChangePasswordSerializer, \
    MyTokenSerializer, ResetPasswordSerializer
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView


class MyTokenView(TokenObtainPairView):
    serializer_class = MyTokenSerializer


class MyTokenRefreshView(TokenRefreshView):
    pass


class UserRegisterView(APIView):
    serializer_class = UserSerializer
    permission_classes = [AllowAny]
    skip_active_check = True

    def post(self, request):
        password = request.data.get('password')
        confirm_password = request.data.get('confirm_password')
        if confirm_password != password:
            return Response({"message": "passwords are not match"}, status=400)

        ser_data = self.serializer_class(data=request.data)
        if ser_data.is_valid():
            user = ser_data.save()
            user.set_password(ser_data.validated_data['password'])
            user.is_active = True
            user.save()
            return Response(ser_data.data, status=200)
        return Response(ser_data.errors, status=400)


class EmailVerificationView(APIView):
    serializer_class = EmailVerificationSerializer
    skip_active_check = True

    def get(self, request):
        email = request.headers.get("Email")
        users = UserModel.objects.filter(email=email)
        if not users:
            return Response({"message": "this email has signed up"}, status=400)
        else:
            user = users[0]
        code, created = OTPCodeModel.objects.get_or_create(user=user)
        if not created:
            code.reset_code()
        code.send_otp_code()
        return Response({
            "message": "Code has been Sent."
        })

    def post(self, request):
        serializer = self.serializer_class(data=request.data,
                                           context={'request': request})
        email = request.headers.get("Email")
        users = UserModel.objects.filter(email=email)
        if not users:
            return Response({"message": "this email hasn\'t signed up"}, status=400)
        else:
            user = users[0]
        code = OTPCodeModel.objects.get(user=user).code
        if serializer.is_valid() and code == serializer.validated_data['code']:
            user.is_email_verified = True
            user.save()
            return Response({
                "message": "email has been verified"
            })
        else:
            return Response({
                "message": "code is wrong"
            }, status=400)


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data, context={'request': request})
        user = request.user
        current_password = serializer.validated_data['current_password']
        new_password = serializer.validated_data['new_password']
        confirm_new_password = serializer.validated_data['confirm_new_password']

        if user.check_password(current_password):
            if new_password == confirm_new_password:
                user.set_password(new_password)
                user.save()
                return Response({"message": "password has changed."})
            else:
                return Response({"message": "new passwords are not same!"}, status=400)
        else:
            return Response({"message": "current password is wrong!"}, status=400)


class CustomAuthToken(ObtainAuthToken):
    serializer_class = AuthTokenSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data,
                                           context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, created = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user_id': user.pk,
            'email': user.email
        })


class UserDetailsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ser_data = UserSerializer(instance=request.user)
        return Response(ser_data.data)


class UpdateUserView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data.copy()
        if 'password' in data:
            del data['password']
        ser_data = UserSerializer(instance=request.user, data=data, partial=True)
        if ser_data.is_valid():
            ser_data.save()
            return Response({'message': 'profile is updated'})
        return Response(ser_data.errors, status=400)


class ResetPasswordSendEmailView(APIView):
    serializer_class = EmailVerificationSerializer
    skip_active_check = True

    def get(self, request):
        email = request.headers.get("Email")
        users = UserModel.objects.filter(email=email)
        if not users:
            return Response({"message": "code has been sent"}, status=200)
        else:
            user = users[0]
        code, created = OTPCodeModel.objects.get_or_create(user=user)
        if not created:
            code.reset_code()
        code.send_otp_code()
        return Response({
            "message": "Code has been Sent."
        })

    def post(self, request):
        serializer = self.serializer_class(data=request.data,
                                           context={'request': request})
        email = request.headers.get("Email")
        users = UserModel.objects.filter(email=email)
        if not users:
            return Response({"message": "code is wrong"}, status=400)
        else:
            user = users[0]
        code = OTPCodeModel.objects.get(user=user).code
        if serializer.is_valid() and code == serializer.validated_data['code']:
            token, created = ResetPasswordTokenModel.objects.get_or_create(user=user)
            token.generate_hash()
            token.save()
            return Response({
                "message": "code is true",
                "hash": str(token.hash)
            })
        else:
            return Response({
                "message": "code is wrong"
            }, status=400)


class ResetPasswordView(APIView):
    serializer_class = ResetPasswordSerializer
    skip_active_check = True

    def post(self, request):
        email = request.headers.get("email")
        hash_ = request.headers.get("reset-password-hash")
        users = UserModel.objects.filter(email=email)
        if not users:
            return Response({"message": "you are not able to change the password"}, status=200)
        else:
            user = users[0]
        tokens = ResetPasswordTokenModel.objects.filter(user=user, hash=hash_)

        if not tokens:
            return Response({"message": "you are not able to change the password"}, status=400)

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_password = serializer.validated_data['new_password']
        confirm_new_password = serializer.validated_data['confirm_new_password']
        if new_password == confirm_new_password:
            user.set_password(new_password)
            user.save()
            return Response({"message": "password has changed"})
        else:
            return Response({"message": "new passwords are not same!"}, status=400)
