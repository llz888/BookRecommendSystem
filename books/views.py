import csv
import json
import math
import re
from django.conf import settings
from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.core.cache import cache  # 顶部引入缓存模块
from django.core.paginator import Paginator  # 记得在顶部导入分页器
from django.db import IntegrityError, transaction
from django.db.models import Q, Count, Sum, Avg, Case, When, Prefetch
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe  # 导入用于渲染 HTML 的工具
from django.views.decorators.csrf import csrf_exempt
from openai import OpenAI

from .forms import BookForm  # 记得在顶部导入
from .forms import UserRegisterForm
from .models import Book, Rating, UserProfile, Shelf, ReadingLog, ReadingHistory
from .recommender import get_user_cf_recommendations


def index(request):
    """
    首页视图：
    1. 整合 UserProfile 统计字段。
    2. 实现混合推荐逻辑。
    3. 增加“正在阅读”进度统计。
    4. 统计最近 7 天真实阅读时长。
    """
    query = request.GET.get('q', '')
    books = Book.objects.all()

    # 基础搜索逻辑
    if query:
        books = books.filter(
            Q(title__icontains=query) | Q(author__icontains=query) | Q(isbn__icontains=query)
        )

    # 获取全站热门书籍
    hot_books = Book.objects.annotate(num_ratings=Count('rating')).order_by('-num_ratings')[:6]

    recommend_books = []
    reading_stats = {}
    current_reading = None
    chart_data = {'labels': [], 'durations': []}

    if request.user.is_authenticated:
        # 1. 更新用户画像
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        profile.update_stats()

        # 2. “正在阅读”进度
        reading_item = Shelf.objects.filter(user=request.user, status='READING').select_related('book').first()
        if reading_item:
            progress_percent = 0
            if reading_item.total_pages and reading_item.total_pages > 0:
                progress_percent = int((reading_item.current_page / reading_item.total_pages) * 100)
            current_reading = {'book': reading_item.book, 'progress': progress_percent}

            # 3. 【核心优化】混合推荐策略：协同过滤 -> 偏好分类 -> 全站热门
            if profile.is_approved:
                recommend_books = []

                # 策略一：尝试基于用户的协同过滤 (User-CF)
                cf_book_ids = get_user_cf_recommendations(request.user, top_k_users=5, top_n_items=4)
                if cf_book_ids:
                    # 获取对象时保持算法算出的排序
                    # 获取对象时保持算法算出的排序
                    preserved_order = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(cf_book_ids)])
                    recommend_books = list(Book.objects.filter(id__in=cf_book_ids).order_by(preserved_order))

                # 策略二：如果协同过滤算出的书不足 4 本（比如新用户，这就是冷启动问题）
                if len(recommend_books) < 4:
                    # 找出用户已读或已推荐的 ID 排除掉
                    exclude_ids = [b.id for b in recommend_books]
                    exclude_ids.extend(Rating.objects.filter(user=request.user).values_list('book_id', flat=True))

                    # 计算用户的偏好分类
                    user_ratings = Rating.objects.filter(user=request.user, score__gte=4)
                    target_cats = list(user_ratings.values_list('book__category', flat=True).distinct())

                    if not target_cats:
                        if profile.favorite_categories:
                            target_cats.extend(profile.favorite_categories.split(','))
                        elif profile.fav_category != "未分类":
                            target_cats.append(profile.fav_category)

                    # 基于分类获取高分图书补齐数量
                    if target_cats:
                        needed_count = 4 - len(recommend_books)
                        content_based_books = Book.objects.filter(category__in=target_cats) \
                            .exclude(id__in=exclude_ids) \
                            .annotate(avg_score=Avg('rating__score')) \
                            .order_by('-avg_score')[:needed_count]
                        recommend_books.extend(list(content_based_books))

            # 策略三：终极兜底（未通过审核、未登录、或没有任何匹配项时）
            if not recommend_books:
                recommend_books = hot_books[:4]
        # 4. 【核心修复】真实阅读趋势统计
        today = timezone.now().date()
        date_list = [today - timedelta(days=i) for i in range(6, -1, -1)]

        # 注意：此处将 updated_at__date__gte 修改为 last_read_date__gte
        daily_logs = ReadingLog.objects.filter(
            user=request.user,
            last_read_date__gte=date_list[0]
        ).annotate(date=TruncDate('last_read_date')).values('date').annotate(total_dur=Sum('read_duration'))

        duration_map = {log['date']: log['total_dur'] for log in daily_logs}

        # 重置 chart_data 确保数据干净
        chart_data = {'labels': [], 'durations': []}
        for d in date_list:
            chart_data['labels'].append(d.strftime('%m-%d'))
            # 确保获取到的时长是整数，避免 null 或 float 导致前端图表异常
            chart_data['durations'].append(int(duration_map.get(d, 0) or 0))

        # 5. 看板数据
        total_min = ReadingLog.objects.filter(user=request.user).aggregate(total=Sum('read_duration'))['total'] or 0
        history_logs = ReadingHistory.objects.filter(user=request.user)
        active_days = len(set(log.viewed_at.date() for log in history_logs))
        avg_score = Rating.objects.filter(user=request.user).aggregate(Avg('score'))['score__avg'] or 0.0

        reading_stats = {
            'total_books': profile.total_books_read,
            'total_hours': round(total_min / 60, 1),
            'avg_rating': round(avg_score, 1),
            'continuous_days': active_days,
        }

    context = {
        'books': books,
        'hot_books': hot_books,
        'query': query,
        'recommend_books': recommend_books,
        'reading_stats': reading_stats,
        'current_reading': current_reading,
        'chart_data': chart_data,
    }
    return render(request, 'index.html', context)


# ==========================================
# 大模型调用相关代码
# ==========================================

client = OpenAI(
    base_url=settings.AI_BASE_URL,
    api_key=settings.AI_API_KEY,
    timeout=settings.AI_TIMEOUT,
)


def discover(request):
    """发现图书视图：支持分类、关键词和评分过滤"""
    query = request.GET.get('q', '').strip()
    category_name = request.GET.get('category', '').strip()
    # 新增：获取用户选择的最低评分，默认为 0
    min_score = request.GET.get('min_score', '0')
    try:
        min_score_val = float(min_score)
    except ValueError:
        min_score_val = 0.0

    # 1. 获取所有有效的分类名称
    raw_categories = Book.objects.values_list('category', flat=True) \
        .exclude(Q(category__isnull=True) | Q(category='')) \
        .distinct()

    category_list = []
    for cat in raw_categories:
        category_list.append({
            'name': cat,
            'is_active': (cat == category_name)
        })

    # 2. 基础查询：通过 annotate 计算出每本书的平均分
    # 这样我们才能根据平均分进行过滤
    books = Book.objects.annotate(avg_score=Avg('rating__score'))

    # 3. 应用过滤逻辑
    if category_name:
        books = books.filter(category=category_name)
    if query:
        books = books.filter(
            Q(title__icontains=query) | Q(author__icontains=query) | Q(isbn__icontains=query)
        )
    # 新增：评分过滤（只显示平均分大于等于用户设定值的书）
    if min_score_val > 0:
        books = books.filter(avg_score__gte=min_score_val)

    context = {
        'books': books,
        'new_categories': category_list,
        'current_category': category_name,
        'query': query,
        'min_score': min_score_val,  # 传回前端保持滑块状态
    }
    return render(request, 'discover.html', context)


def register_user(request):
    """处理新用户注册"""
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False
            user.save()
            UserProfile.objects.create(user=user, is_approved=False)
            messages.success(request, '注册成功！请等待管理员审核。')
            return redirect('login')
    else:
        form = UserRegisterForm()
    return render(request, 'register.html', {'form': form})


def login_user(request):
    if request.method == 'POST':
        # 现在单选框在 form 内了，这里能正常获取到 'admin' 或 'reader'
        identity = request.POST.get('identity')
        form = AuthenticationForm(request, data=request.POST)

        if form.is_valid():
            user = authenticate(username=form.cleaned_data.get('username'),
                                password=form.cleaned_data.get('password'))
            if user is not None:
                # 登录用户
                login(request, user)

                # 判断跳转逻辑
                if identity == 'admin':
                    if user.is_staff:
                        return redirect('my_admin')  # 管理员跳转到后台
                    else:
                        logout(request)  # 如果不是管理员却选了管理员登录，强制退出并报错
                        messages.error(request, '该账号没有管理员权限！')
                        return redirect('login')

                return redirect('home')  # 读者跳转到首页
        else:
            messages.error(request, '账号或密码错误。')
    else:
        form = AuthenticationForm()
    return render(request, 'user_login.html', {'form': form})


def logout_user(request):
    """退出登录"""
    logout(request)
    return redirect('home')


@login_required
def profile_settings(request):
    # 1. 获取当前登录用户的 Profile 对象
    # 使用 get_or_create 避免因为某些原因 Profile 不存在而报错
    user_profile, created = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        # 2. 获取表单数据
        nickname = request.POST.get('nickname')
        bio = request.POST.get('bio')
        avatar = request.FILES.get('avatar')

        try:
            # 3. 更新 UserProfile 字段
            # 注意：不要去动 request.user.username，除非你确实想改用户名
            user_profile.nickname = nickname
            user_profile.bio = bio

            if avatar:
                user_profile.avatar = avatar

            # 4. 仅保存 Profile 对象
            user_profile.save()

            messages.success(request, "个人资料已更新！")
            return redirect('profile_settings')
        except Exception as e:
            messages.error(request, f"保存失败: {e}")

    return render(request, 'profile_settings.html')


@staff_member_required
def admin_dashboard(request):
    """后台仪表盘：动态统计数据"""
    # 1. 基础统计
    total_users = User.objects.filter(is_staff=False).count()
    total_books = Book.objects.count()

    # 2. 动态折线图数据：统计最近 7 天的阅读活跃度
    today = timezone.now().date()
    # 生成最近 7 天的日期列表 [6天前, ..., 今天]
    date_list = [today - timedelta(days=i) for i in range(6, -1, -1)]
    date_labels = [d.strftime('%m-%d') for d in date_list]

    # 查询最近7天的阅读历史记录，按天统计浏览量
    daily_stats = ReadingHistory.objects.filter(
        viewed_at__date__gte=date_list[0]
    ).annotate(date=TruncDate('viewed_at')).values('date').annotate(count=Count('id'))
    # 将查询结果映射为字典 {datetime.date: count}
    stats_map = {item['date']: item['count'] for item in daily_stats}
    # 按照 date_list 的顺序填充数据，当天没数据的填 0
    chart_values = [stats_map.get(d, 0) for d in date_list]
    # ... 原有的折线图代码保留 ...

    # 【新增】1. 为饼图提供数据（图书分类统计）
    category_data = list(Book.objects.values('category').annotate(count=Count('id')).order_by('-count')[:8])
    pie_data = [{'name': item['category'], 'value': item['count']} for item in category_data]

    # 【新增】2. 为横向柱状图提供数据（热门推荐图书转化率/热度Top5）
    hot_books_data = list(Book.objects.annotate(num_ratings=Count('rating')).order_by('-num_ratings')[:5])
    bar_labels = [b.title for b in hot_books_data]
    bar_values = [b.num_ratings for b in hot_books_data]

    context = {
        'total_users': total_users,
        'total_books': total_books,
        'chart_labels': date_labels,
        'chart_values': chart_values,
        # 把新增的数据传给前端
        'pie_data': pie_data,
        'bar_labels': bar_labels,
        'bar_values': bar_values,
    }
    return render(request, 'admin_dashboard.html', context)
    context = {
        'total_users': total_users,
        'total_books': total_books,
        'chart_labels': date_labels,  # 传递动态日期标签
        'chart_values': chart_values,  # 传递动态统计数值
    }
    return render(request, 'admin_dashboard.html', context)


def book_detail(request, book_id):
    book = get_object_or_404(Book, id=book_id)
    # 获取该书的所有评价
        # 只取顶级评论：回复由模板在每条评论下方展示，单独预取
    ratings = (
        Rating.objects.filter(book=book, parent__isnull=True)
        .select_related('user')
        .prefetch_related(
            'likes',
            Prefetch('replies', queryset=Rating.objects.select_related('user').order_by('create_time')),
        )
        .annotate(like_count=Count('likes'))
        .order_by('-create_time')
    )

    avg_score = round(
        Rating.objects.filter(book=book, parent__isnull=True)
        .aggregate(avg=Avg('score'))['avg'] or 0.0,
        1,
    )

    in_shelf = False
    progress_percent = 0
    if request.user.is_authenticated:
        ReadingHistory.objects.update_or_create(
            user=request.user,
            book=book,
            defaults={'viewed_at': timezone.now()}
        )
    # 获取用户的书架进度信息
    if request.user.is_authenticated:
        shelf_item = Shelf.objects.filter(user=request.user, book=book).first()
        if shelf_item:
            in_shelf = True
            if shelf_item.total_pages > 0:
                progress_percent = int((shelf_item.current_page / shelf_item.total_pages) * 100)

    context = {
        'book': book,
        'ratings': ratings,
        'avg_score': avg_score,  # 现在这里不会再报错了
        'in_shelf': in_shelf,
        'progress_percent': progress_percent,
    }
    return render(request, 'book_detail.html', context)


# 新增一个专门给前端异步调用的接口
@login_required
@login_required
def api_get_ai_recommend(request):
    """异步获取AI推荐语并缓存"""
    cache_key = f'ai_recommend_{request.user.id}'

    # 1. 尝试从缓存读取
    ai_reason = cache.get(cache_key)

    # 2. 核心修改：如果缓存为空，或者缓存里存的是之前的报错信息，就强制重新调用
    if not ai_reason or "调用失败" in ai_reason:
        ai_reason = get_ai_recommendations(request.user)

        # 3. 只有在真正调用成功时，才把结果写入缓存 (防止脏数据又被存 12 小时)
        if "调用失败" not in ai_reason:
            cache.set(cache_key, ai_reason, timeout=43200)
        else:
            # 如果依然失败，就顺便把旧缓存清掉
            cache.delete(cache_key)

    return JsonResponse({'status': 'success', 'reason': ai_reason})


def get_ai_recommendations(user):
    """调用本地 DeepSeek 生成推荐语"""
    try:
        # 1. 获取用户画像数据 (使用 get_or_create 更安全)
        # 1. 获取用户画像数据 (防弹写法)
        try:
            profile = UserProfile.objects.get(user=user)
        except UserProfile.DoesNotExist:
            profile = UserProfile.objects.create(user=user)

        # 获取用户给出 4 分以上的高分书籍
        high_ratings = Rating.objects.filter(user=user, score__gte=4).select_related('book')[:3]

        # 2. 构建提示词 (Prompt)
        user_pref = profile.favorite_categories if profile.favorite_categories else "未设置偏好"
        read_history = "、".join([r.book.title for r in high_ratings]) if high_ratings else "刚注册，暂无阅读记录"

        prompt = f"""
        你是一个专业的图书推荐助手。请根据以下用户信息进行分析：
        - 用户的阅读偏好分类：{user_pref}
        - 用户非常喜欢的书籍：{read_history}

        任务：请为该用户写一段 100 字左右的个性化推荐导语，鼓励他继续阅读，并简要提到为什么这些内容适合他。
        注意：直接输出推荐语，不要包含任何旁白或前言。
        """

        # 3. 发送请求给本地 DeepSeek
        response = client.chat.completions.create(
            model=settings.AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"调用失败，具体报错信息为：{str(e)}"


@csrf_exempt
def ai_chat_api(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            # 💡 强制只取最后一条消息，不发历史记录，排除 Token 堆积导致的死机
            full_history = data.get('history', [])
            user_message = full_history[-1]['content'] if full_history else "你好"

            # 💡 增加系统指令，要求它不要思考，直接给结果
            response = client.chat.completions.create(
                model=settings.AI_MODEL,
                messages=[
                    {"role": "system", "content": "你是一个图书助手。请直接、简短地回答，不要输出思考过程。"},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.1,  # 降低随机性，减少资源占用
                stream=False  # 💡 核心：强制非流式，一次性返回
            )

            ai_reply = response.choices[0].message.content
            return JsonResponse({'status': 'success', 'reply': ai_reply})
        except Exception as e:
            # 💡 这里的报错非常重要，请看 Django 运行的黑窗口
            print(f"Ollama 调用异常: {e}")
            return JsonResponse({'status': 'error', 'reply': f'模型响应超时，请重启Ollama。'})
    return JsonResponse({'status': 'error', 'reply': '请求方式错误'})


def read_book(request, book_id):
    book = get_object_or_404(Book, id=book_id)
    content = ""

    # 1. 读取文本内容
    if book.content_file:
        try:
            with open(book.content_file.path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (UnicodeDecodeError, FileNotFoundError):
            try:
                with open(book.content_file.path, 'r', encoding='gbk') as f:
                    content = f.read()
            except:
                content = "无法读取书籍内容。"

    # --- 核心：分页基础数据 ---
    PAGE_SIZE = 500
    total_length = len(content)
    total_pages = math.ceil(total_length / PAGE_SIZE) if total_length > 0 else 1

    # 2. 章节识别与目录生成逻辑 (已加入智能截断处理，防止混入正文)
    chapter_pattern = re.compile(r'(第[0-9一二三四五六七八九十百]+[章节回].*)')
    chapters = []
    toc = []

    for match in chapter_pattern.finditer(content):
        start_idx = match.start()
        raw_title = match.group(1).strip()

        # --- 智能截断逻辑 ---
        parts = raw_title.split()
        # 大多数小说的章节名格式为 "第一章 标题"
        # 如果空格分出了很多段（>3），说明后面大概率紧跟了正文，我们只取前3段作为章节名
        if len(parts) > 3:
            title = " ".join(parts[:3])
        else:
            title = raw_title

        # 再加一层保险，强制限制长度，如果还超长就暴力截断
        if len(title) > 25:
            title = title[:25] + "..."
        # --------------------

        chap_page = math.floor(start_idx / PAGE_SIZE) + 1

        chapters.append({'start': start_idx, 'title': title})
        toc.append({'title': title, 'page': chap_page})

    # 3. 分页与进度恢复逻辑
    page_param = request.GET.get('page')

    if page_param:
        try:
            current_page = int(page_param)
        except:
            current_page = 1
    elif request.user.is_authenticated:
        shelf_item = Shelf.objects.filter(user=request.user, book=book).first()
        if shelf_item and shelf_item.current_page > 0:
            current_page = shelf_item.current_page
        else:
            current_page = 1
    else:
        current_page = 1

    current_page = max(1, min(current_page, total_pages))

    start_index = (current_page - 1) * PAGE_SIZE
    end_index = start_index + PAGE_SIZE
    page_content = content[start_index:end_index]

    # 4. 判断当前所属章节
    current_chapter_title = "正文"
    for chap in reversed(chapters):
        if start_index >= chap['start']:
            current_chapter_title = chap['title']
            break

    # 5. 实时保存当前进度
    if request.user.is_authenticated:
        ReadingHistory.objects.update_or_create(
            user=request.user, book=book,
            defaults={'viewed_at': timezone.now()}
        )
        shelf_item, created = Shelf.objects.get_or_create(
            user=request.user,
            book=book,
            defaults={'status': 'READING'}
        )
        # 注意：这里你原代码中有两句重复的 get_or_create，我保留了你的逻辑，
        # 只是确保赋值正确
        shelf_item.current_page = current_page
        shelf_item.total_pages = total_pages

        if current_page >= total_pages and total_pages > 1:
            shelf_item.status = 'READ'
        elif shelf_item.status == 'WANT':
            shelf_item.status = 'READING'

        shelf_item.save()

    # 👇【核心新增】：如果是 AJAX 无刷新请求，仅返回 JSON 数据
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get(
            'Accept') == 'application/json':
        return JsonResponse({
            'content': page_content,
            'current_page': current_page,
            'total_pages': total_pages,
            'current_chapter': current_chapter_title,
            'has_previous': current_page > 1,
            'has_next': current_page < total_pages,
        })

    # 6. 正常首次打开网页，渲染 HTML 模板
    context = {
        'book': book,
        'content': page_content,
        'current_page': current_page,
        'total_pages': total_pages,
        'current_chapter': current_chapter_title,
        'has_previous': current_page > 1,
        'has_next': current_page < total_pages,
        'toc': toc,
    }
    return render(request, 'read_book.html', context)


@login_required
def my_bookshelf(request):
    """书架视图：获取当前用户书架上的所有书籍"""
    # 获取所有书架项，并关联查询书籍信息，按最后更新时间倒序排列
    all_items = Shelf.objects.filter(user=request.user).select_related('book').order_by('-updated_at')

    context = {
        'all_items': all_items,
    }
    return render(request, 'my_bookshelf.html', context)


@login_required
def toggle_shelf(request, book_id):
    """点击按钮快速切换状态或加入书架"""
    if request.method == "POST":
        status = request.POST.get('status')
        book = get_object_or_404(Book, id=book_id)

        if status == "REMOVE":
            Shelf.objects.filter(user=request.user, book=book).delete()
        else:
            Shelf.objects.update_or_create(
                user=request.user, book=book,
                defaults={'status': 'WANT'}
            )
            # 💡 核心优化：智能返回到用户刚才所在的页面
            referer = request.META.get('HTTP_REFERER')
            if referer:
                return redirect(referer)
        return redirect('book_detail', book_id=book.id)


@login_required
def update_reading_time(request):
    """异步更新阅读时长（心跳接口）"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            book_id = data.get('book_id')
            # 每次前端发来心跳，代表阅读了 1 分钟
            minutes = int(data.get('minutes', 1))

            book = Book.objects.get(id=book_id)

            # 查找是否已经有这本书的阅读记录，没有则创建
            log, created = ReadingLog.objects.get_or_create(
                user=request.user,
                book=book,
                defaults={'read_duration': 0}
            )

            # 累加阅读时长并保存
            log.read_duration += minutes
            log.save()

            return JsonResponse({'status': 'success', 'total_duration': log.read_duration})
        except Exception as e:
            return JsonResponse({'status': 'error', 'msg': str(e)})

    return JsonResponse({'status': 'error', 'msg': '请求方式错误'})


@login_required
def view_history(request):
    """浏览历史视图：关联书架进度展示"""
    # 获取历史记录
    history_qs = ReadingHistory.objects.filter(user=request.user).select_related('book').order_by('-viewed_at')[:50]

    # 为了拿到进度，我们需要获取该用户书架上的所有信息并做成字典映射
    shelf_dict = {item.book_id: item for item in Shelf.objects.filter(user=request.user)}

    history_items = []
    for h in history_qs:
        # 尝试匹配书架里的进度
        shelf_info = shelf_dict.get(h.book.id)
        percent = 0
        if shelf_info and shelf_info.total_pages > 0:
            percent = int((shelf_info.current_page / shelf_info.total_pages) * 100)

        history_items.append({
            'book': h.book,
            'viewed_at': h.viewed_at,
            'progress': percent  # 这里的进度是实时计算的
        })

    return render(request, 'view_history.html', {'history_items': history_items})


@login_required
def submit_comment(request, book_id):
    """提交书评或回复"""
    if request.method == "POST":
        book = get_object_or_404(Book, id=book_id)
        score = request.POST.get('score', 5)
        comment_text = request.POST.get('comment', '').strip()
        parent_id = request.POST.get('parent_id') or None  # 回复时传入父评论 id

        if not comment_text:
            return redirect('book_detail', book_id=book_id)

        # 同一用户对同一本书只能有一条顶级评论，同一父评论也只能回复一次
        if Rating.objects.filter(user=request.user, book=book, parent_id=parent_id).exists():
            if parent_id is None:
                messages.error(request, '你已经评论过这本书了，同一本书只能发表一条书评。')
            else:
                messages.error(request, '你已经回复过这条评论了。')
            return redirect('book_detail', book_id=book_id)

        try:
            Rating.objects.create(
                user=request.user,
                book=book,
                score=score,
                comment=comment_text,
                parent_id=parent_id
            )
        except IntegrityError:
            # 并发下两个请求同时通过上面的检查时，由数据库唯一索引兜底
            messages.error(request, '提交失败：你已经评论过这本书了。')
    return redirect('book_detail', book_id=book_id)


@login_required
def toggle_like(request, rating_id):
    """点赞/取消点赞的异步接口"""
    rating = get_object_or_404(Rating, id=rating_id)
    if rating.likes.filter(id=request.user.id).exists():
        rating.likes.remove(request.user)
        action = "unliked"
    else:
        rating.likes.add(request.user)
        action = "liked"

    return JsonResponse({
        'status': 'success',
        'action': action,
        'total_likes': rating.total_likes()
    })


@login_required
def my_activities(request):
    """查看我的评分、评论和点赞记录"""
    # 使用 select_related 优化查询，确保关联的图书封面能直接获取
    my_ratings = Rating.objects.filter(user=request.user, parent=None) \
        .select_related('book') \
        .order_by('-create_time')

    # 获取点赞记录，同时预加载书籍和发布该评价的用户
    liked_ratings = request.user.liked_ratings.all() \
        .select_related('book', 'user') \
        .order_by('-create_time')

    context = {
        'my_ratings': my_ratings,
        'liked_ratings': liked_ratings,
    }
    return render(request, 'my_activities.html', context)


def user_stats_api(request):
    """为个人中心提供可视化数据"""
    user = request.user
    if not user.is_authenticated:
        return JsonResponse({'status': 'error'}, status=403)

    # 1. 阅读分类分布数据
    category_data = Rating.objects.filter(user=user) \
        .values('book__category') \
        .annotate(count=Count('id')) \
        .order_by('-count')

    # 2. 最近7天阅读活跃度（模拟数据或从 ReadingHistory 提取）
    # ...

    data = {
        'categories': [item['book__category'] for item in category_data],
        'counts': [item['count'] for item in category_data],
    }
    return JsonResponse(data)


@staff_member_required
def batch_import_books(request):
    """
    通过 CSV 文件批量导入图书（管理员专属）
    """
    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')

        if not csv_file or not csv_file.name.endswith('.csv'):
            messages.error(request, "请上传有效的 CSV 格式文件！")
            return redirect('admin_dashboard')

        # 兼容 Excel 导出的 GBK 编码和标准的 UTF-8 编码
        file_data = csv_file.read()
        try:
            decoded_file = file_data.decode('utf-8').splitlines()
        except UnicodeDecodeError:
            decoded_file = file_data.decode('gbk').splitlines()

        reader = csv.DictReader(decoded_file)
        books_to_create = []

        # 遍历 CSV 行构建对象，但不立即保存
        for row in reader:
            # 假设你的 CSV 表头有 title, author, category, isbn
            # 这里使用了 .get() 来防止某列缺失导致报错
            title = row.get('title')
            if not title:  # 书名不能为空
                continue

            book = Book(
                title=title,
                author=row.get('author', '未知'),
                category=row.get('category', '未分类'),
                isbn=row.get('isbn', ''),
                # 如果还有其他字段可以在这里补充
            )
            books_to_create.append(book)

        # 【毕设核心亮点】：使用 bulk_create 进行批量插入，性能极高！
        try:
            with transaction.atomic():  # 开启数据库事务，保证数据一致性
                # ignore_conflicts=True 可以忽略重复的 ISBN 等唯一键冲突（适用于 SQLite/PostgreSQL）
                Book.objects.bulk_create(books_to_create, batch_size=500, ignore_conflicts=True)

            messages.success(request, f"成功批量导入 {len(books_to_create)} 本图书！")
        except Exception as e:
            messages.error(request, f"导入失败，数据库错误：{str(e)}")

        return redirect('admin_dashboard')


@staff_member_required
def custom_admin_book_list(request):
    """
    自定义的后台图书管理列表页：支持模糊搜索与分页
    """
    # 1. 获取搜索关键词
    query = request.GET.get('q', '').strip()

    # 2. 获取所有图书，默认按最新添加排序
    book_list = Book.objects.all().order_by('-id')

    # 3. 核心搜索：支持书名、作者、ISBN 的多字段搜索
    if query:
        book_list = book_list.filter(
            Q(title__icontains=query) |
            Q(author__icontains=query) |
            Q(isbn__icontains=query)
        )

    # 4. 加入分页功能，每页显示 10 本书
    paginator = Paginator(book_list, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # 5. 将 query 传回前端，用于搜索框回显
    return render(request, 'custom_admin_books.html', {
        'page_obj': page_obj,
        'query': query
    })


@staff_member_required
def add_book(request):
    """手动新增单本图书"""
    if request.method == 'POST':
        form = BookForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "图书新增成功！")
            return redirect('custom_admin_books')
    else:
        form = BookForm()

    return render(request, 'admin_add_book.html', {'form': form})


@staff_member_required
def custom_admin_user_list(request):
    """自定义用户审核中心列表"""
    # 获取所有读者（排除管理员自身），按创建时间倒序
    # select_related('user') 优化查询，减少数据库压力
    profiles = UserProfile.objects.select_related('user').filter(user__is_staff=False).order_by('-user__date_joined')

    # 统计数据：待审核人数
    pending_count = profiles.filter(is_approved=False).count()

    return render(request, 'custom_admin_users.html', {
        'profiles': profiles,
        'pending_count': pending_count
    })


@staff_member_required
def approve_user(request, profile_id):
    """处理用户审核动作"""
    if request.method == 'POST':
        profile = get_object_or_404(UserProfile, id=profile_id)
        action = request.POST.get('action')

        if action == 'approve':
            # 审核通过：激活 User 账号并标记 Profile 已审核
            profile.is_approved = True
            profile.user.is_active = True
            profile.user.save()
            profile.save()
            messages.success(request, f"用户 {profile.user.username} 已审核通过，现可正常登录。")
        elif action == 'reject':
            # 拒绝审核：这里选择直接删除该账号（或者你可以增加一个 status 字段标记拒绝）
            username = profile.user.username
            profile.user.delete()
            messages.warning(request, f"已拒绝并清理用户 {username} 的注册申请。")

    return redirect('custom_admin_user_list')


@staff_member_required
def edit_user(request, profile_id):
    """管理员编辑用户信息：包括资料、头像、密码和审核状态"""
    profile = get_object_or_404(UserProfile, id=profile_id)
    user = profile.user
    if request.method == 'POST':
        # 1. 修改基本信息
        profile.nickname = request.POST.get('nickname')
        profile.bio = request.POST.get('bio')
        profile.fav_category = request.POST.get('fav_category') or "未设置"

        # 2. 修改审核状态 (Checkbox 处理)
        profile.is_approved = 'is_approved' in request.POST
        # 同步激活/禁用 Django 账号
        user.is_active = profile.is_approved

        # 3. 修改头像
        if 'avatar' in request.FILES:
            profile.avatar = request.FILES['avatar']

        # 4. 修改密码 (如果输入框不为空则修改)
        new_password = request.POST.get('new_password')
        if new_password and new_password.strip():
            user.set_password(new_password)

        user.save()
        profile.save()
        messages.success(request, f"用户 {user.username} 的资料已成功更新！")
        return redirect('custom_admin_user_list')

    return render(request, 'admin_edit_user.html', {'profile': profile})


@staff_member_required
def edit_book(request, book_id):
    """自定义后台：编辑图书信息"""
    book = get_object_or_404(Book, id=book_id)

    if request.method == 'POST':
        # instance=book 是关键，它告诉 Django 这是在修改现有的对象，而不是新建
        form = BookForm(request.POST, request.FILES, instance=book)
        if form.is_valid():
            form.save()
            messages.success(request, f"图书《{book.title}》已更新成功！")
            return redirect('custom_admin_books')
    else:
        # GET 请求时，同样传入 instance 让表单带上初始值
        form = BookForm(instance=book)

    return render(request, 'admin_edit_book.html', {'form': form, 'book': book})


@staff_member_required
def custom_admin_rating_list(request):
    """自定义后台：书评言论管理列表"""
    # 获取所有评价，关联查询用户和书籍以减少 SQL 查询次数
    ratings_list = Rating.objects.select_related('user', 'book').order_by('-create_time')

    # 分页，每页 15 条
    paginator = Paginator(ratings_list, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'custom_admin_ratings.html', {'page_obj': page_obj})


@staff_member_required
def delete_rating_admin(request, rating_id):
    """管理员删除评论，并支持撤销"""
    if request.method == 'POST':
        rating = get_object_or_404(Rating, id=rating_id)

        # 1. 在删除前，将数据序列化存入 Session 备份
        # 注意：这里我们备份书名、用户名ID、评分和内容
        request.session['last_deleted_rating'] = {
            'user_id': rating.user.id,
            'book_id': rating.book.id,
            'score': rating.score,
            'comment': rating.comment,
            'create_time': rating.create_time.strftime('%Y-%m-%d %H:%M:%S')
        }

        content_snippet = (rating.comment[:10] + '...') if rating.comment else "无文字内容"
        rating.delete()

        # 2. 构建带“撤销”链接的消息
        # 我们使用 mark_safe 让消息里的 <a> 标签生效
        undo_url = reverse('undo_delete_rating')
        msg = mark_safe(
            f"已成功删除评论：'{content_snippet}'。 "
            f"<a href='{undo_url}' class='alert-link text-decoration-underline'>点此撤销删除</a>"
        )
        messages.success(request, msg)

    return redirect('custom_admin_rating_list')


@staff_member_required
def undo_delete_rating(request):
    """撤销上一次删除操作"""
    data = request.session.get('last_deleted_rating')

    if data:
        # 从 Session 中还原对象
        Rating.objects.create(
            user_id=data['user_id'],
            book_id=data['book_id'],
            score=data['score'],
            comment=data['comment'],
            create_time=data['create_time']
        )
        # 还原后清除 Session，防止重复撤销
        del request.session['last_deleted_rating']
        messages.success(request, "已成功撤销删除，书评已恢复！")
    else:
        messages.error(request, "无法撤销，可能撤销已过期或没有删除记录。")

    return redirect('custom_admin_book_list')  # 跳转回图书列表页，方便查看导入结果
