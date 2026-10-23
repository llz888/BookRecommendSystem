from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import Book


class UserRegisterForm(UserCreationForm):
    """用户注册表单"""
    username = forms.CharField(label="用户名", help_text="")
    email = forms.EmailField(label="电子邮箱", required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def clean_password1(self):
        password = self.cleaned_data.get("password1")
        if len(password) < 8:
            raise ValidationError("密码长度不能低于 8 个字符。")
        return password

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].help_text = "密码长度不低于 8 位。"
        self.fields['password2'].help_text = "请再次输入密码以确认。"


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        # 定义表单显示的字段
        fields = ['title', 'author', 'category', 'isbn', 'pic_url', 'content_file']
        # 为字段添加 Bootstrap 样式
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '请输入书名'}),
            'author': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '请输入作者'}),
            'category': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '请输入分类'}),
            'isbn': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '请输入 ISBN'}),
            'pic_url': forms.FileInput(attrs={'class': 'form-control'}),
            'content_file': forms.FileInput(attrs={'class': 'form-control'}),
        }
