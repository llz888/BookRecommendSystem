from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import Book
from .models import UserProfile


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


class UserProfileForm(forms.ModelForm):
    """个人资料设置表单"""
    # 显式添加 Email 字段，用于同步修改 User 表的数据
    email = forms.EmailField(
        label="电子邮箱",
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = UserProfile
        # 对应 models.py 中的实际字段
        fields = ['avatar', 'favorite_categories']
        labels = {
            'avatar': '上传头像',
            'favorite_categories': '偏好分类',
        }
        widgets = {
            'avatar': forms.FileInput(attrs={'class': 'form-control'}),
            'favorite_categories': forms.TextInput(attrs={
                'placeholder': '例如：编程, 文学, 科幻 (用逗号隔开)',
                'class': 'form-control'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 页面加载时，将 User 表中的当前邮箱作为初始值
        if self.instance and self.instance.user:
            self.fields['email'].initial = self.instance.user.email

    def clean_email(self):
        """防止邮箱被其他用户占用"""
        email = self.cleaned_data.get('email')
        user = self.instance.user
        if User.objects.filter(email=email).exclude(pk=user.pk).exists():
            raise ValidationError("该邮箱已被其他用户注册。")
        return email

    def save(self, commit=True):
        """同步保存 UserProfile 和 User 的邮箱"""
        profile = super().save(commit=False)
        user = profile.user
        # 将表单中的 email 赋值给关联的 user 对象
        user.email = self.cleaned_data['email']
        user.save()
        if commit:
            profile.save()
        return profile


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
