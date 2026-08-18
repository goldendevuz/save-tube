from unfold.forms import UserCreationForm as UnfoldUserCreationForm
from unfold.widgets import BASE_INPUT_CLASSES


class RegisterForm(UnfoldUserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs["class"] = " ".join(BASE_INPUT_CLASSES)
        self.fields["password1"].widget.attrs["autofocus"] = False