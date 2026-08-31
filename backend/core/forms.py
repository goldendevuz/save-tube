from unfold.forms import UserCreationForm as UnfoldUserCreationForm
from unfold.widgets import BASE_INPUT_CLASSES
from unfold.forms import AuthenticationForm as UnfoldAuthenticationForm


class SaveTubeLoginForm(UnfoldAuthenticationForm):
    error_messages = {
        **UnfoldAuthenticationForm.error_messages,
        "invalid_login": "Username yoki parol noto'g'ri. Qaytadan urinib ko'ring.",
        "inactive": "Bu akkaunt faol emas.",
    }


class RegisterForm(UnfoldUserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop("usable_password", None)
        self.fields["username"].widget.attrs["class"] = " ".join(BASE_INPUT_CLASSES)
        self.fields["password1"].widget.attrs["autofocus"] = False