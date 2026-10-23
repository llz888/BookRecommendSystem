from django.contrib.auth.models import User
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from books.models import Book, Rating


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
