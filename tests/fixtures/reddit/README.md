# Reddit Raw Fixtures

These files are raw Reddit responses downloaded for parser, ingestion, and matching
development. Each request uses `limit=5` and the user agent
`chattersift-dev-fixtures/0.1 by local`.

Reddit `.rss` endpoints currently return Atom XML, so those responses are stored
with `.atom` filenames.

## Coverage

- Single subreddit post listings: `r/django`, `r/Python`
- Multi-subreddit post listing: `r/django+Python`
- Sitewide keyword search
- Sitewide multi-keyword search
- Subreddit keyword search
- Multi-subreddit keyword search
- Single subreddit recent comments
- Multi-subreddit recent comments
- Single post comment tree
- JSON-only comment search URL samples

## Source URLs

Post listings:

| Fixture | URL |
| --- | --- |
| `raw/single_subreddit_django_new.json` | `https://www.reddit.com/r/django/new.json?limit=5&raw_json=1` |
| `raw/single_subreddit_django_new.atom` | `https://www.reddit.com/r/django/new.rss?limit=5` |
| `raw/single_subreddit_python_new.json` | `https://www.reddit.com/r/Python/new.json?limit=5&raw_json=1` |
| `raw/single_subreddit_python_new.atom` | `https://www.reddit.com/r/Python/new.rss?limit=5` |
| `raw/multi_subreddit_django_python_new.json` | `https://www.reddit.com/r/django+Python/new.json?limit=5&raw_json=1` |
| `raw/multi_subreddit_django_python_new.atom` | `https://www.reddit.com/r/django+Python/new.rss?limit=5` |

Keyword searches:

| Fixture | URL |
| --- | --- |
| `raw/keyword_sitewide_htmx.json` | `https://www.reddit.com/search.json?q=htmx&sort=new&limit=5&raw_json=1` |
| `raw/keyword_sitewide_htmx.atom` | `https://www.reddit.com/search.rss?q=htmx&sort=new&limit=5` |
| `raw/keywords_sitewide_django_htmx_postgres.json` | `https://www.reddit.com/search.json?q=%28django%20OR%20htmx%20OR%20postgres%29&sort=new&limit=5&raw_json=1` |
| `raw/keywords_sitewide_django_htmx_postgres.atom` | `https://www.reddit.com/search.rss?q=%28django%20OR%20htmx%20OR%20postgres%29&sort=new&limit=5` |
| `raw/keyword_subreddit_django_postgres.json` | `https://www.reddit.com/r/django/search.json?q=postgres&restrict_sr=1&sort=new&limit=5&raw_json=1` |
| `raw/keyword_subreddit_django_postgres.atom` | `https://www.reddit.com/r/django/search.rss?q=postgres&restrict_sr=1&sort=new&limit=5` |
| `raw/keyword_multi_subreddit_django_python_postgres.json` | `https://www.reddit.com/r/django+Python/search.json?q=postgres&restrict_sr=1&sort=new&limit=5&raw_json=1` |
| `raw/keyword_multi_subreddit_django_python_postgres.atom` | `https://www.reddit.com/r/django+Python/search.rss?q=postgres&restrict_sr=1&sort=new&limit=5` |

Comment feeds:

| Fixture | URL |
| --- | --- |
| `raw/single_subreddit_django_comments.json` | `https://www.reddit.com/r/django/comments.json?limit=5&raw_json=1` |
| `raw/single_subreddit_django_comments.atom` | `https://www.reddit.com/r/django/comments.rss?limit=5` |
| `raw/multi_subreddit_django_python_comments.json` | `https://www.reddit.com/r/django+Python/comments.json?limit=5&raw_json=1` |
| `raw/multi_subreddit_django_python_comments.atom` | `https://www.reddit.com/r/django+Python/comments.rss?limit=5` |

Post comment tree:

| Fixture | URL |
| --- | --- |
| `raw/post_comment_tree_django.json` | `https://www.reddit.com/r/django/comments/1t4puon/zeroconfig_django_profiler_see_which_views_raise.json?limit=5&raw_json=1` |
| `raw/post_comment_tree_django.atom` | `https://www.reddit.com/r/django/comments/1t4puon/zeroconfig_django_profiler_see_which_views_raise.rss?limit=5` |
| `raw/comment_tree_source_permalink.txt` | `r/django/comments/1t4puon/zeroconfig_django_profiler_see_which_views_raise` |

Comment search samples:

| Fixture | URL |
| --- | --- |
| `raw/comment_search_sitewide_django.json` | `https://www.reddit.com/search.json?q=django&type=comment&sort=new&limit=5&raw_json=1` |
| `raw/comment_search_subreddit_django_postgres.json` | `https://www.reddit.com/r/django/search.json?q=postgres&type=comment&restrict_sr=1&sort=new&limit=5&raw_json=1` |
| `raw/comment_search_multi_subreddit_django_python_htmx.json` | `https://www.reddit.com/r/django+Python/search.json?q=htmx&type=comment&restrict_sr=1&sort=new&limit=5&raw_json=1` |

## Caveat

The public `search.json` endpoint accepts `type=comment`, but current responses
may still contain post objects (`kind: "t3"`) rather than comment objects. The
comment search fixtures are intentionally kept as raw endpoint samples so tests
can document and handle that behavior explicitly.
