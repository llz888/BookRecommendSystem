from django.contrib.auth.models import User  # 使用Django自带的用户系统
from django.db import models
from django.db.models import Count


# 1. 图书信息表
class Book(models.Model):
    title = models.CharField(max_length=200, verbose_name="书名")
    author = models.CharField(max_length=100, verbose_name="作者")
    isbn = models.CharField(max_length=20, unique=True, verbose_name="ISBN")
    category = models.CharField(max_length=50, verbose_name="分类")
    description = models.TextField(verbose_name="简介")
    # --- 修改这里：将 URLField 改为 CharField，避免 URL 格式校验 ---
    pic_url = models.CharField(max_length=255, blank=True, verbose_name="封面图链接/路径")
    add_time = models.DateTimeField(auto_now_add=True, verbose_name="入库时间")
    # 新增：用于上传电子书 TXT 文件的字段
    content_file = models.FileField(upload_to='book_texts/', null=True, blank=True, verbose_name="电子书文件")

    class Meta:
        verbose_name = "图书"
        verbose_name_plural = "图书管理"

    def __str__(self):
        return self.title


# BookRecommendSystem/books/models.py

class Rating(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="用户")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, verbose_name="图书")
    score = models.IntegerField(default=0, verbose_name="评分(1-5)")
    comment = models.TextField(blank=True, null=True, verbose_name="书评内容")
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="评价时间")

    # --- 新增功能字段 ---
    # 1. 实现回复功能：指向自身（Rating）的自关联外键
    # 如果 parent 为空，说明是顶级评论；如果不为空，说明是对某条评论的回复
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies',
        verbose_name="父级评论"
    )

    # 2. 实现点赞功能：多对多关系，记录哪些用户点赞了这条评论
    likes = models.ManyToManyField(
        User,
        blank=True,
        related_name='liked_ratings',
        verbose_name="点赞用户"
    )

    class Meta:
        # 注意：有了回复功能后，unique_together 需要根据业务权衡。
        # 如果允许用户在同一本书下多次回复他人，建议移除这个限制，
        # 或者在逻辑层判断“只有顶级评论（parent=None）”才唯一。
        unique_together = ('user', 'book', 'parent')
        verbose_name = "评分与书评"
        verbose_name_plural = "书评管理中心"

    def total_likes(self):
        """返回总点赞数"""
        return self.likes.count()

    def __str__(self):
        if self.parent:
            return f"{self.user.username} 回复了评论 ID:{self.parent.id}"
        return f"{self.user.username} 评 {self.book.title} ({self.score}星)"


# 3. 阅读日志表 (分析系统的核心数据)
class ReadingLog(models.Model):
    # 为外键添加 verbose_name
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="用户")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, verbose_name="图书")

    # 该字段已包含 verbose_name
    read_duration = models.IntegerField(default=0, verbose_name="阅读时长(分钟)")
    updated_at = models.DateTimeField(auto_now=True)  # 每次 save() 时自动更新时间
    # 为日期字段添加 verbose_name
    last_read_date = models.DateTimeField(auto_now=True, verbose_name="最近阅读时间")

    class Meta:
        # 定义模型在后台显示的单数和复数名称
        verbose_name = "阅读日志"
        verbose_name_plural = "阅读日志管理"

    def __str__(self):
        return f"{self.user.username} - {self.book.title} 的阅读记录"


from django.contrib.auth.models import User


class UserProfile(models.Model):
    # 使用 related_name='profile' 方便从 User 对象反向查询
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')

    # 对应开题报告：个人信息管理中的头像
    avatar = models.ImageField(upload_to='avatars/', default='default.png', verbose_name="头像")

    # 新增：记录偏好分类（动态计算的结果）
    fav_category = models.CharField(max_length=100, default="未分类", verbose_name="最爱阅读类型")

    # 存储用户手动选择或系统分析的多项偏好
    favorite_categories = models.CharField(max_length=200, blank=True, verbose_name="偏好分类")

    # 核心：审核状态（用于毕设中提到的“用户管理”功能）
    is_approved = models.BooleanField(default=False, verbose_name="是否已审核")

    # 新增：累计阅读书籍数
    total_books_read = models.IntegerField(default=0, verbose_name="已读完书籍")

    def update_stats(self):
        """
        动态更新统计数据：
        1. 根据评分记录计算出现频率最高的分类作为 fav_category
        2. 根据阅读历史统计阅读过的书籍总数
        """
        from .models import Rating, ReadingHistory

        # 1. 更新最爱阅读类型 (根据用户评分过的图书分类进行统计)
        top_category = Rating.objects.filter(user=self.user) \
            .values('book__category') \
            .annotate(count=Count('book__category')) \
            .order_by('-count').first()

        if top_category:
            self.fav_category = top_category['book__category']

        # 2. 更新已读完书籍总数 (统计阅读历史中的去重书籍数)
        read_count = ReadingHistory.objects.filter(user=self.user) \
            .values('book') \
            .distinct().count()

        self.total_books_read = read_count

        # 3. 保存更新
        self.save()

    class Meta:
        verbose_name = "用户资料"
        verbose_name_plural = "用户审核"

    def __str__(self):
        return f"{self.user.username} 的资料"


class Shelf(models.Model):
    STATUS_CHOICES = [
        ('WANT', '想读'),
        ('READING', '在读'),
        ('READ', '已读'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="用户")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, verbose_name="图书")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='WANT', verbose_name="状态")
    # 记录阅读到第几页（用于“在读”状态）
    last_page = models.IntegerField(default=1, verbose_name="最后阅读页码")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    current_page = models.IntegerField('当前页码', default=0)
    total_pages = models.IntegerField('总页码', default=0)

    class Meta:
        unique_together = ('user', 'book')
        verbose_name = "书架记录"
        verbose_name_plural = "书架管理"


class ReadingHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="用户")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, verbose_name="书籍")
    viewed_at = models.DateTimeField(auto_now=True, verbose_name="浏览时间")

    class Meta:
        ordering = ['-viewed_at']
        unique_together = ('user', 'book')  # 保证同一个用户看同一本书只占一条记录，仅更新时间
