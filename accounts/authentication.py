from .models import UserModel


class EmailBackend:
    def authenticate(self, request, email=None, password=None):
        try:
            user = UserModel.objects.get(email=email)
            if user.check_password(password):
                print("password is wrong")
                return user
            return None
        except UserModel.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return UserModel.objects.get(id=user_id)
        except UserModel.DoesNotExist:
            return None
