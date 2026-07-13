from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from . import views

app_name = 'accounts'

urlpatterns = [
    path('token/', views.MyTokenView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', views.MyTokenRefreshView.as_view(), name='token_refresh'),
    path('register/', views.UserRegisterView.as_view(), name='user_register'),
    path('profile/', views.UserDetailsView.as_view(), name='user-details'),
    path('profile/update/', views.UpdateUserView.as_view(), name='user-update'),
    path('email-verification/', views.EmailVerificationView.as_view(), name='email-verification'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change-password'),
    path('reset-password-send-email/', views.ResetPasswordSendEmailView.as_view(), name='reset-password-send-email'),
    path('reset-password/', views.ResetPasswordView.as_view(), name='reset-password'),
]
