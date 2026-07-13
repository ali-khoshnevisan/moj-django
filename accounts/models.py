import uuid

from django.db import models
import random
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin


class UserManager(BaseUserManager):
    def create_user(self, name, email, password):
        if not name:
            raise ValueError('user must have last name!')
        if not email:
            raise ValueError('user must have email!')
        user = self.model(name=name, email=self.normalize_email(email))
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, name, email, password):
        user = self.create_user(name, email, password)
        user.is_admin = True
        user.is_superuser = True
        user.is_staff = True
        user.save()
        return user


def user_profile_image_path(instance, filename):
    return f'accounts/user_{instance.pk}/profile_image/{filename}'


class UserModel(AbstractBaseUser, PermissionsMixin):
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    profile_image = models.ImageField(blank=True, null=True, upload_to=user_profile_image_path)
    is_email_verified = models.BooleanField(default=False)
    registration_date = models.DateField(auto_now_add=True)
    is_admin = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']


def random_code():
    return "111111"


class OTPCodeModel(models.Model):
    user = models.OneToOneField(UserModel, primary_key=True, on_delete=models.CASCADE)
    code = models.CharField(max_length=6, default=random_code)

    def reset_code(self):
        self.code = random_code()
        self.save()

    def send_otp_code(self):
        # try:
        #     api = KavenegarAPI(
        #         '364172347A732F79384D46713577756E49396B384A7958694471715A32496F342F5449446970796C7872773D')
        #     params = {
        #         'sender': '',
        #         'receptor': self.phone_number,
        #         'message': f'کد تایید شما {self.code}',
        #     }
        #     response = api.sms_send(params=params)
        #     print(response)
        # except APIException as e:
        #     print(e)
        # except HTTPException as e:
        #     print(e)
        #         =========================================

        pass


class ResetPasswordTokenModel(models.Model):
    user = models.ForeignKey(UserModel, on_delete=models.CASCADE)
    hash = models.UUIDField(blank=True, null=True)

    def generate_hash(self):
        self.hash = uuid.uuid4()
        self.save()
