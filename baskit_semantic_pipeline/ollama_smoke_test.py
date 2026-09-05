from semantic_ai import SemanticEngine

TESTS = [
    'דאב - דאודורנט רול און לאישה מלפפון 50 מ"ל * שלישייה',
    'תנובה - גבינת פטה 16%',
    'GOOD PHARM - בקבוק שתייה טריטן 750 מ"ל ורוד',
    'סנו - שקיות אשפה גדול 30 יחידות',
]


def main():
    engine = SemanticEngine()

    for text in TESTS:
        result = engine.parse(text)
        print("=" * 80)
        print(text)
        print(result)


if __name__ == "__main__":
    main()
