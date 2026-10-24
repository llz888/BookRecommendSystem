from django.contrib import admin
from .models import AIUsage, Book, UserProfile, Rating, ReadingLog

# 修改后台标题
admin.site.site_header = '智能图书推荐与阅读分析系统 - 管理端'
admin.site.site_title = '系统管理中心'
admin.site.index_title = '全局数据概览'


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    # 列表页显示的字段
    list_display = ('isbn', 'title', 'author', 'category', 'rating_count')
    # 搜索框
    search_fields = ('title', 'author', 'isbn')
    # 右侧过滤器
    list_filter = ('category',)
    # 分页设置
    list_per_page = 15

    # 自定义显示字段：统计评分人数（对应阅读分析需求）
    def rating_count(self, obj):
        return obj.rating_set.count()

    rating_count.short_description = '累计评价数'


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_approved', 'favorite_categories')
    list_editable = ('is_approved',)  # 允许在列表页直接勾选审核
    actions = ['approve_users']

    def approve_users(self, request, queryset):
        # 批量审核动作
        queryset.update(is_approved=True)
        # 同时激活 User 账号
        for profile in queryset:
            profile.user.is_active = True
            profile.user.save()
        self.message_user(request, "选中的用户已成功通过审核！")

    approve_users.short_description = "批量审核通过"


# 注册其他模型，方便管理数据
admin.site.register(Rating)
admin.site.register(ReadingLog)


@admin.register(AIUsage)
class AIUsageAdmin(admin.ModelAdmin):
    list_display = ('user', 'date', 'count')
    list_filter = ('date',)
    ordering = ('-date', 'user')
