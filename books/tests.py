import json
import types
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from books.forms import UserRegisterForm
from books.models import Book, Rating, ReadingHistory, Shelf, UserProfile


def make_book(isbn, title='测试书'):
    return Book.objects.create(
        title=title, author='测试作者', isbn=isbn,
        category='文学', description='用于测试的简介',
    )


class CommentRuleTests(TestCase):
    """书评规则：同一用户对同一本书只能有一条顶级评论，对同一父评论只能回复一次。"""

    def setUp(self):
        self.book = make_book('TEST-0001')
        self.other_book = make_book('TEST-0002', title='另一本书')
        self.user = User.objects.create_user(username='tester', password='pass12345')
        self.client.force_login(self.user)

    def post_comment(self, book, comment='测试评论', parent_id=None):
        return self.client.post(
            f'/book/{book.id}/comment/',
            {'score': 5, 'comment': comment, 'parent_id': parent_id or ''},
        )

    def test_duplicate_top_level_comment_is_rejected(self):
        self.post_comment(self.book, '第一次')
        self.post_comment(self.book, '第二次')
        self.assertEqual(
            Rating.objects.filter(user=self.user, book=self.book, parent__isnull=True).count(),
            1,
        )

    def test_same_user_can_comment_another_book(self):
        self.post_comment(self.book)
        self.post_comment(self.other_book)
        self.assertEqual(Rating.objects.filter(user=self.user).count(), 2)

    def test_database_blocks_duplicate_even_when_view_is_bypassed(self):
        Rating.objects.create(user=self.user, book=self.book, score=5, comment='第一条')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Rating.objects.create(user=self.user, book=self.book, score=5, comment='绕过视图')

    def test_duplicate_reply_to_same_parent_is_blocked(self):
        parent = Rating.objects.create(user=self.user, book=self.book, score=5, comment='父评论')
        replier = User.objects.create_user(username='replier', password='pass12345')
        self.client.force_login(replier)
        self.post_comment(self.book, '回复一', parent_id=parent.id)
        self.post_comment(self.book, '回复二', parent_id=parent.id)
        self.assertEqual(Rating.objects.filter(parent=parent).count(), 1)


class BookDetailQueryCountTests(TestCase):
    """详情页 SQL 条数必须与评论数无关，防止 N+1 回归。"""

    def setUp(self):
        self.book = make_book('TEST-0100')
        self.viewer = User.objects.create_user(username='viewer', password='pass12345')
        for i in range(2):
            reader = User.objects.create_user(username=f'reader{i}', password='pass12345')
            Rating.objects.create(user=reader, book=self.book, score=5, comment='评论')
        self.client.force_login(self.viewer)

    def get_detail_query_count(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(f'/book/{self.book.id}/')
        self.assertEqual(response.status_code, 200)
        return len(ctx)

    def test_query_count_is_stable_when_comments_grow(self):
        # 首次访问会创建浏览历史（INSERT），之后是更新（UPDATE），语句数不同，先预热一次
        self.get_detail_query_count()
        before = self.get_detail_query_count()
        for i in range(2, 8):
            reader = User.objects.create_user(username=f'reader{i}', password='pass12345')
            Rating.objects.create(user=reader, book=self.book, score=5, comment='评论')
        after = self.get_detail_query_count()
        self.assertEqual(before, after, '评论数增加后 SQL 条数发生了变化，疑似 N+1 回归')


class UserProfileStatsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='stats', password='pass12345')
        self.profile = UserProfile.objects.create(user=self.user)
        lit1 = make_book('STATS-1')
        lit2 = make_book('STATS-2')
        tech = make_book('STATS-3', title='科技书')
        tech.category = '科技'
        tech.save()
        Rating.objects.create(user=self.user, book=lit1, score=5, comment='a')
        Rating.objects.create(user=self.user, book=lit2, score=4, comment='b')
        Rating.objects.create(user=self.user, book=tech, score=3, comment='c')
        ReadingHistory.objects.create(user=self.user, book=lit1)
        ReadingHistory.objects.create(user=self.user, book=tech)

    def test_update_stats_computes_category_and_count(self):
        self.profile.update_stats()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.fav_category, '文学')
        self.assertEqual(self.profile.total_books_read, 2)


class ShelfRuleTests(TestCase):
    def test_duplicate_shelf_entry_rejected(self):
        user = User.objects.create_user(username='shelf', password='pass12345')
        book = make_book('SHELF-1')
        Shelf.objects.create(user=user, book=book)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Shelf.objects.create(user=user, book=book)

    def test_reading_history_keeps_single_row(self):
        user = User.objects.create_user(username='history', password='pass12345')
        book = make_book('HIST-1')
        for _ in range(3):
            ReadingHistory.objects.update_or_create(
                user=user, book=book, defaults={'viewed_at': timezone.now()},
            )
        self.assertEqual(ReadingHistory.objects.filter(user=user, book=book).count(), 1)


class UserRegisterFormTests(TestCase):
    def test_short_password_rejected(self):
        form = UserRegisterForm(data={
            'username': 'newuser', 'email': 'new@example.com',
            'password1': '1234567', 'password2': '1234567',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('password1', form.errors)

    def test_valid_registration_accepted(self):
        form = UserRegisterForm(data={
            'username': 'newuser', 'email': 'new@example.com',
            'password1': '12345678', 'password2': '12345678',
        })
        self.assertTrue(form.is_valid(), form.errors)


class ProfileSettingsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='profile', password='pass12345')
        self.profile = UserProfile.objects.create(user=self.user)
        self.client.force_login(self.user)

    def test_nickname_and_bio_are_saved(self):
        self.client.post('/profile/', {'nickname': '书虫', 'bio': '爱读书'})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.nickname, '书虫')
        self.assertEqual(self.profile.bio, '爱读书')

    def test_non_image_avatar_rejected(self):
        upload = SimpleUploadedFile('x.pdf', b'%PDF-1.4', content_type='application/pdf')
        self.client.post('/profile/', {'nickname': 'a', 'bio': 'b', 'avatar': upload})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.avatar.name, 'default.png')


class CommentScoreTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='scorer', password='pass12345')
        self.book = make_book('SCORE-1')
        self.client.force_login(self.user)

    def posted_score(self, score):
        self.client.post(
            f'/book/{self.book.id}/comment/',
            {'score': score, 'comment': '评分测试'},
        )
        return Rating.objects.get(user=self.user, book=self.book, parent__isnull=True).score

    def test_non_numeric_score_defaults_to_five(self):
        self.assertEqual(self.posted_score('abc'), 5)

    def test_score_above_range_clamped_to_five(self):
        self.assertEqual(self.posted_score('99'), 5)

    def test_score_below_range_clamped_to_one(self):
        self.assertEqual(self.posted_score('-3'), 1)


class AdminAccessTests(TestCase):
    def test_staff_can_open_dashboard(self):
        staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get('/my-admin/').status_code, 200)

    def test_normal_user_cannot_open_dashboard(self):
        user = User.objects.create_user(username='normal', password='pass12345')
        self.client.force_login(user)
        response = self.client.get('/my-admin/')
        self.assertIn(response.status_code, (302, 403))


def fake_ai_client(reply='测试回复'):
    """构造一个不会真正发起网络请求的 AI 客户端替身。"""
    def create(**kwargs):
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=reply))]
        )
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))


class AIEndpointTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='aiuser', password='pass12345')
        self.client.force_login(self.user)

    def post_chat(self):
        return self.client.post(
            '/api/chat/',
            data=json.dumps({'history': [{'role': 'user', 'content': '你好'}]}),
            content_type='application/json',
        )

    def test_anonymous_user_cannot_call_ai(self):
        self.client.logout()
        response = self.post_chat()
        self.assertEqual(response.status_code, 401)
        self.assertIn('登录', response.json()['reply'])

    def test_anonymous_user_cannot_get_ai_recommendation(self):
        self.client.logout()
        response = self.client.get('/api/ai-recommend/')
        self.assertEqual(response.status_code, 401)
        self.assertIn('登录', response.json()['reply'])

    def test_get_request_is_rejected(self):
        self.assertEqual(self.client.get('/api/chat/').status_code, 405)

    @override_settings(AI_DAILY_QUOTA=1, AI_RATE_LIMIT_PER_MIN=100)
    @patch('books.views.get_ai_client')
    def test_daily_quota_is_enforced(self, mock_get_client):
        mock_get_client.return_value = fake_ai_client()
        self.assertEqual(self.post_chat().status_code, 200)
        self.assertEqual(self.post_chat().status_code, 429)

    @override_settings(AI_RATE_LIMIT_PER_MIN=1, AI_DAILY_QUOTA=100)
    @patch('books.views.get_ai_client')
    def test_rate_limit_is_enforced(self, mock_get_client):
        mock_get_client.return_value = fake_ai_client()
        self.assertEqual(self.post_chat().status_code, 200)
        self.assertEqual(self.post_chat().status_code, 429)

    @override_settings(AI_API_KEY='')
    def test_missing_api_key_returns_friendly_error(self):
        response = self.post_chat()
        self.assertEqual(response.status_code, 200)
        self.assertIn('未配置', response.json()['reply'])
