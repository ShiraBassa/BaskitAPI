import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from .ollama_client import OllamaClient
from .response_parser import items_from_response, text


CATEGORIES = [
    'מוצרי חלב', 'בשר ועוף', 'דגים ופירות ים', 'ירקות', 'פירות',
    'חטיפים וממתקים', 'שתייה קלה', 'אלכוהול ויין', 'מוצרי ניקיון',
    'טואלטיקה והיגיינה', 'מוצרי בית וכלים', 'צעצועים ומשחקים',
    'מוצרי חשמל', 'קמפינג וטיולים', 'ביגוד והנעלה', 'אפייה וקינוחים'
]


class CategoryClassifier:
    SYSTEM = '''אתה מסווג מוצרי סופרמרקט בעברית למחלקות קמעונאיות.
group_name הוא כבר שם מוצר כללי ומנורמל.
הבן את המשמעות של ה-group_name כמכלול.
העדף קטגוריה מהרשימה כאשר היא באמת מתאימה באופן טבעי וברור.
אל תכריח התאמה חלשה רק כדי להשתמש ברשימה.
אם אף קטגוריה מהרשימה אינה מתאימה באמת, צור קטגוריה חדשה קצרה וברורה.
יצירת קטגוריה חדשה היא אפשרות אחרונה.
אל תסווג לפי מילה בודדת.
אל תתרגם.
אל תסביר.
החזר JSON בלבד.'''


    def __init__(self, client=None, batch_size=6, workers=4, categories=None):
        self.client = client or OllamaClient()
        self.batch_size = batch_size
        self.workers = workers
        self.categories = categories or CATEGORIES

    def _batch(self, groups):
        schema = {
            'type': 'object',
            'properties': {
                'categories': {
                    'type': 'object',
                    'properties': {
                        group: {
                            'type': 'string',
                            'enum': self.categories,
                        }
                        for group in groups
                    },
                    'required': list(groups),
                    'additionalProperties': False,
                },
            },
            'required': ['categories'],
            'additionalProperties': False,
        }
        user = (
            'סווג כל group_name ל-category אחת. '
            'החזר JSON יחיד בדיוק במבנה {"categories":{"group_name":"category"}}. '
            'המפתח חייב להיות ה-group_name עצמו, והערך חייב להיות הקטגוריה שנבחרה עבורו. '
            'אסור להפוך את הכיוון. אסור להשתמש בשם קטגוריה כמפתח. '
            'חייב להיות מפתח לכל group_name שקיבלת. '
            'העדף קטגוריה מהרשימה כאשר היא באמת מתאימה באופן טבעי וברור. '
            'אל תכריח התאמה חלשה רק כדי להשתמש ברשימה. '
            'אם אף קטגוריה מהרשימה אינה מתאימה באמת, אפשר ליצור קטגוריה חדשה קצרה וברורה. '
            'אל תסווג לפי מילה בודדת. הבן את המשמעות של ה-group_name כמכלול. '
            'אל תתרגם. אל תסביר. JSON בלבד.\n'
            'SUPERMARKET_CATEGORIES:\n'
            + json.dumps(self.categories, ensure_ascii=False, separators=(',', ':'))
            + '\nGROUP_NAMES:\n'
            + json.dumps(groups, ensure_ascii=False, separators=(',', ':'))
        )

        p = self.client.payload(
            self.SYSTEM,
            user,
            schema,
            max(256, len(groups) * 24),
        )
        parsed, raw = self.client.chat(p)
        out = {}

        if isinstance(parsed, dict):
            categories = parsed.get('categories')
            expected = set(groups)
            if isinstance(categories, dict) and set(categories) == expected:
                for group_name in groups:
                    category = text(categories.get(group_name))
                    if category in self.categories:
                        out[group_name] = category

        if len(out) < len(groups):
            print(
                f'[WARNING] Category AI batch returned {len(out)}/{len(groups)} '
                f'results matching the required group_name -> category contract; raw response length: {len(raw or "")}; '
                f'raw response: {raw!r}'
            )

        return out

    def classify(self, groups, cached=None):
        cached = cached or {}
        out = {g: cached[g] for g in groups if cached.get(g)}
        missing = [g for g in groups if g not in out]

        batches = [
            missing[i:i + self.batch_size]
            for i in range(0, len(missing), self.batch_size)
        ]

        if batches:
            with ThreadPoolExecutor(max_workers=min(self.workers, len(batches))) as ex:
                futures = [ex.submit(self._batch, batch) for batch in batches]
                for f in as_completed(futures):
                    try:
                        out.update(f.result())
                    except Exception as e:
                        print(f'[WARNING] Category AI batch failed: {e}')

        missing = [g for g in missing if g not in out]

        if missing:
            print(
                f'[WARNING] Category AI omitted {len(missing)} group(s); '
                'retrying individually.'
            )
            with ThreadPoolExecutor(max_workers=min(self.workers, len(missing))) as ex:
                futures = [ex.submit(self._batch, [g]) for g in missing]
                for f in as_completed(futures):
                    try:
                        out.update(f.result())
                    except Exception as e:
                        print(f'[WARNING] Category AI recovery failed: {e}')

        return out