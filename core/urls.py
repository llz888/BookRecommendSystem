from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from books import views
from books.views import batch_import_books
from books.views import custom_admin_book_list

urlpatterns = [
    # 后台与首页
    path('admin/', admin.site.urls),
    path('my-admin/', views.admin_dashboard, name='my_admin'),
    path('', views.index, name='home'),
    # 确保导入了 add_book
    path('admin-dashboard/add-book/', views.add_book, name='add_book'),
    # 登录注册相关
    path('register/', views.register_user, name='register'),
    path('login/', views.login_user, name='login'),
    path('logout/', views.logout_user, name='logout'),
    path('admin-dashboard/users/', views.custom_admin_user_list, name='custom_admin_user_list'),
    path('admin-dashboard/users/approve/<int:profile_id>/', views.approve_user, name='approve_user'),
    # 个人资料（只保留这一个即可，它包含了展示和修改功能）
    path('profile/', views.profile_settings, name='profile_settings'),
    # 新增：“发现”页面的路由
    path('discover/', views.discover, name='discover'),
    # 新增：图书详情页路由 (<int:book_id> 用于接收书本的动态ID)
    path('book/<int:book_id>/', views.book_detail, name='book_detail'),
    path('api/chat/', views.ai_chat_api, name='ai_chat_api'),  # 新增这一行！
    # 新增这一行：在线阅读路由
    path('book/<int:book_id>/read/', views.read_book, name='read_book'),
    path('my-shelf/', views.my_bookshelf, name='my_bookshelf'),
    path('shelf/toggle/<int:book_id>/', views.toggle_shelf, name='toggle_shelf'),
    # 在 urlpatterns 列表中添加这一行：
    path('api/ai-recommend/', views.api_get_ai_recommend, name='api_ai_recommend'),
    path('api/update_reading_time/', views.update_reading_time, name='update_reading_time'),
    path('history/', views.view_history, name='view_history'),
    # 新增：提交评论/回复的路由
    path('book/<int:book_id>/comment/', views.submit_comment, name='submit_comment'),
    path('admin-dashboard/import/', batch_import_books, name='batch_import_books'),
    # 新增：点赞的异步接口路由
    path('rating/like/<int:rating_id>/', views.toggle_like, name='toggle_like'),
    path('my-activities/', views.my_activities, name='my_activities'),
    path('admin-dashboard/custom-books/', custom_admin_book_list, name='custom_admin_books'),
    path('admin-dashboard/users/edit/<int:profile_id>/', views.edit_user, name='edit_user'),
    # 确保导入了新视图函数
    path('admin-dashboard/ratings/', views.custom_admin_rating_list, name='custom_admin_rating_list'),
    path('admin-dashboard/ratings/delete/<int:rating_id>/', views.delete_rating_admin, name='delete_rating_admin'),
    # 确保导入了新视图函数
    path('admin-dashboard/books/edit/<int:book_id>/', views.edit_book, name='edit_book'),
    # 确保导入了 undo_delete_rating
    path('admin-dashboard/ratings/undo/', views.undo_delete_rating, name='undo_delete_rating'),

]

# 最佳实践：仅在开发环境（DEBUG=True）下让 Django 代理媒体文件
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
