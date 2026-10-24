"""基于用户的协同过滤（User-CF）推荐。

三层优化：
1. 索引缓存：评分索引按 TTL 缓存在进程内，避免每次请求重复读取全表并重建结构。
2. 候选剪枝：只在「与目标用户评过同一本书」的用户中计算相似度，不遍历全体用户。
3. numpy 向量化：范数、点积、Top-K 用数组运算完成，消除 Python 双重循环。
"""

import time

import numpy as np

from .models import Rating

INDEX_TTL_SECONDS = 60

_cache = {'built_at': 0.0, 'index': None}


class RatingIndex:
    """评分数据的紧凑表示，供多次推荐复用。"""

    __slots__ = ('users', 'books', 'scores', 'unique_users', 'unique_books',
                 'norms', 'sorted_users', 'sorted_scores', 'starts', 'ends')

    def __init__(self, users, books, scores, unique_users, unique_books):
        self.users = users
        self.books = books
        self.scores = scores
        self.unique_users = unique_users
        self.unique_books = unique_books

        self.norms = np.zeros(len(unique_users))
        np.add.at(self.norms, users, scores * scores)
        np.sqrt(self.norms, out=self.norms)

        order = np.argsort(books, kind='stable')
        self.sorted_users = users[order]
        self.sorted_scores = scores[order]
        sorted_books = books[order]
        self.starts = np.searchsorted(sorted_books, np.arange(len(unique_books)), side='left')
        self.ends = np.searchsorted(sorted_books, np.arange(len(unique_books)), side='right')


def build_index(rows):
    """把 (user_id, book_id, score) 序列编码成 numpy 索引。"""
    if not rows:
        return None
    data = np.asarray(rows, dtype=np.int64)
    user_ids, book_ids = data[:, 0], data[:, 1]
    scores = data[:, 2].astype(np.float64)
    unique_users, users = np.unique(user_ids, return_inverse=True)
    unique_books, books = np.unique(book_ids, return_inverse=True)
    return RatingIndex(users.astype(np.int32), books.astype(np.int32), scores,
                       unique_users, unique_books)


def recommend_from_index(index, target_user_id, top_k_users=5, top_n_items=4):
    if index is None:
        return []

    position = np.searchsorted(index.unique_users, target_user_id)
    if position >= len(index.unique_users) or index.unique_users[position] != target_user_id:
        return []  # 冷启动：目标用户没有有效评分
    norm_target = index.norms[position]
    if norm_target == 0:
        return []

    target_mask = index.users == position
    target_books = index.books[target_mask]
    target_scores = index.scores[target_mask]

    # 只在共同物品上累加点积，候选用户自动被限制在「评过目标物品」的集合内
    dots = np.zeros(len(index.unique_users))
    for book, score in zip(target_books, target_scores):
        lo, hi = index.starts[book], index.ends[book]
        dots[index.sorted_users[lo:hi]] += score * index.sorted_scores[lo:hi]

    norms = index.norms
    similarities = np.zeros(len(index.unique_users))
    valid = norms > 0
    similarities[valid] = dots[valid] / (norm_target * norms[valid])
    similarities[position] = 0.0

    candidates = np.flatnonzero(similarities > 0)
    if candidates.size == 0:
        return []

    k = min(top_k_users, candidates.size)
    top_users = candidates[np.argpartition(similarities[candidates], -k)[-k:]]
    top_users = top_users[np.argsort(similarities[top_users])[::-1]]

    seen = set(target_books.tolist())
    item_scores = np.zeros(len(index.unique_books))
    for neighbour in top_users:
        mask = index.users == neighbour
        weight = similarities[neighbour]
        for book, score in zip(index.books[mask], index.scores[mask]):
            if book not in seen:
                item_scores[book] += weight * score

    positive = np.flatnonzero(item_scores > 0)
    if positive.size == 0:
        return []

    n = min(top_n_items, positive.size)
    best = positive[np.argpartition(item_scores[positive], -n)[-n:]]
    best = best[np.argsort(item_scores[best])[::-1]]
    return [int(index.unique_books[i]) for i in best]


def recommend_from_ratings(rows, target_user_id, top_k_users=5, top_n_items=4):
    """不经过缓存的单次计算，供单元测试和压测脚本使用。"""
    return recommend_from_index(build_index(rows), target_user_id, top_k_users, top_n_items)


def get_user_cf_recommendations(target_user, top_k_users=5, top_n_items=4):
    """视图入口：复用进程内索引缓存，避免每次请求重复构建。"""
    now = time.monotonic()
    if _cache['index'] is None or now - _cache['built_at'] > INDEX_TTL_SECONDS:
        rows = list(
            Rating.objects.filter(score__gte=3)
            .values_list('user_id', 'book_id', 'score')
        )
        _cache['index'] = build_index(rows)
        _cache['built_at'] = now
    return recommend_from_index(_cache['index'], target_user.id, top_k_users, top_n_items)
