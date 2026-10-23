from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('books', '0011_readinglog_updated_at'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX uniq_rating_user_book_root
                ON books_rating (user_id, book_id, (COALESCE(parent_id, 0)))
            """,
            reverse_sql="DROP INDEX uniq_rating_user_book_root ON books_rating",
        ),
    ]