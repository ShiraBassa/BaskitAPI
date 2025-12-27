import sys
import os
import re

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Classes.userHandler import User
from Data.data_sets import *
from Data.update_db import update_all_stores, clear_all
from Classes.msgBarHandler import msg_bar


def get_all_existing_stores():
    stores_branches = {}
    stores_urls = stores_urls_ref.get()

    for store_name in stores_urls:
        stores_branches[store_name] = []
        
        for branch_name in stores_urls[store_name]:
            stores_branches[store_name].append(branch_name)

    return stores_branches

def regulate_item_names():
    all_codes_map = items_code_name_ref.get() or {}
    
    if not all_codes_map:
        print("No items in items_code_name_ref")
        return

    _raw_name_info = items_name_code_ref.get() or {}
    name_code_map = {
        k: v for k, v in _raw_name_info.items()
        if k and str(k).strip() and v and str(v).strip() and str(v).strip().lower() != "null"
    }

    def _is_valid_code(v):
        return v is not None and str(v).strip() and str(v).strip().lower() != "null"

    groups = {}
    old_name_by_code = {}

    for code, old_name in all_codes_map.items():
        if not _is_valid_code(code):
            continue
        if old_name is None:
            continue

        old_name = str(old_name).strip()
        if not old_name or old_name.lower() == "null":
            continue

        new_name = regulate_single_item_name(old_name)
        if not new_name:
            continue

        code = str(code).strip()
        groups.setdefault(new_name, set()).add(code)
        old_name_by_code[code] = old_name

    if not groups:
        print("No valid regulated groups built")
        return

    code_name_updates = {}
    name_code_updates = {}
    stale_name_deletes = {}

    for regulated_name, codes in groups.items():
        if not codes:
            continue

        existing = name_code_map.get(regulated_name)
        if _is_valid_code(existing):
            canonical_code = str(existing).strip()
        else:
            canonical_code = sorted(list(codes))[0]

        for c in codes:
            code_name_updates[c] = regulated_name

        if not _is_valid_code(existing):
            name_code_updates[regulated_name] = canonical_code
            name_code_map[regulated_name] = canonical_code

        for c in codes:
            old_name = old_name_by_code.get(c)
            if not old_name or old_name == regulated_name:
                continue

            mapped = name_code_map.get(old_name)
            if _is_valid_code(mapped) and str(mapped).strip() in codes:
                stale_name_deletes[old_name] = None

    if code_name_updates:
        items_code_name_ref.update(code_name_updates)

    if stale_name_deletes:
        items_name_code_ref.update(stale_name_deletes)

    if name_code_updates:
        items_name_code_ref.update(name_code_updates)

    # ------------------------------------------------------------------
    # FAST mirroring (adaptive):
    # - Few duplicate codes  -> parallel per-code reads from items_stores
    # - Many duplicate codes -> scan stores_items per store once
    # Behavior stays the same: all codes in group get all store/branch pairs,
    # and BOTH trees are mirrored.
    # ------------------------------------------------------------------

    from concurrent.futures import ThreadPoolExecutor, as_completed

    dup_groups = {reg_name: codes for reg_name, codes in groups.items() if codes and len(codes) >= 2}
    dup_code_set = set()
    for _rn, _codes in dup_groups.items():
        for _c in _codes:
            dup_code_set.add(str(_c).strip())

    # Tuning knobs
    CHUNK = 50000
    BRANCH_FLUSH_THRESHOLD = 20000
    # If we have a lot of dup codes, prefer store-scan (few big requests)
    STORE_SCAN_DUP_CODE_THRESHOLD = 400
    # Parallelism for per-code reads
    MAX_WORKERS = 16

    pending_items_stores = {}
    pending_branch_updates = {}
    pending_branch_count = 0

    def _flush_branch_updates():
        nonlocal pending_branch_updates, pending_branch_count
        for s, bmap in pending_branch_updates.items():
            for b, upd in bmap.items():
                if upd:
                    stores_items_ref.child(s).child(b).update(upd)
        pending_branch_updates = {}
        pending_branch_count = 0

    def _queue_pair(code: str, store: str, branch: str, price):
        nonlocal pending_items_stores, pending_branch_updates, pending_branch_count
        pending_items_stores[f"{code}/{store}/{branch}"] = price
        pending_branch_updates.setdefault(store, {}).setdefault(branch, {})[code] = price
        pending_branch_count += 1

        if len(pending_items_stores) >= CHUNK:
            items_stores_ref.update(pending_items_stores)
            pending_items_stores = {}

        if pending_branch_count >= BRANCH_FLUSH_THRESHOLD:
            _flush_branch_updates()

    total_pairs = 0

    # --------------------------------------------------------------
    # Strategy A: scan stores_items per store (few requests)
    # --------------------------------------------------------------
    def _mirror_via_store_scan():
        nonlocal total_pairs

        # Build quick code->regulated_name
        code_to_reg_name = {}
        for rn, cs in dup_groups.items():
            for c in cs:
                code_to_reg_name[str(c).strip()] = rn

        # regulated_name -> {(store,branch): price}
        reg_sb_price = {}

        stores_urls = stores_urls_ref.get() or {}
        for store in stores_urls.keys():
            store_blob = stores_items_ref.child(store).get() or {}
            if not store_blob:
                continue

            for branch, code_price in (store_blob or {}).items():
                if not code_price:
                    continue

                for code, price in (code_price or {}).items():
                    if price is None:
                        continue
                    c = str(code).strip()
                    if c not in dup_code_set:
                        continue

                    rn = code_to_reg_name.get(c)
                    if not rn:
                        continue

                    reg_sb_price.setdefault(rn, {})[(store, branch)] = price

        # Mirror into both trees
        for rn, codes in dup_groups.items():
            sb_map = reg_sb_price.get(rn)
            if not sb_map:
                continue

            for (store, branch), price in sb_map.items():
                for c in codes:
                    c = str(c).strip()
                    _queue_pair(c, store, branch, price)
                    total_pairs += 1

    # --------------------------------------------------------------
    # Strategy B: parallel per-code reads from items_stores
    # --------------------------------------------------------------
    def _mirror_via_parallel_code_reads():
        nonlocal total_pairs

        # Fetch stores for all dup codes in parallel once
        def _fetch(code: str):
            return code, (items_stores_ref.child(code).get() or {})

        sb_by_code = {}
        codes_list = list(dup_code_set)
        if codes_list:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                futs = [ex.submit(_fetch, c) for c in codes_list]
                for f in as_completed(futs):
                    c, sb = f.result()
                    sb_by_code[c] = sb

        for rn, codes in dup_groups.items():
            # Union across codes
            union_sb_price = {}
            for c in codes:
                c = str(c).strip()
                sb = sb_by_code.get(c) or {}
                for store, branches in (sb or {}).items():
                    if not branches:
                        continue
                    for branch, price in (branches or {}).items():
                        if price is None:
                            continue
                        union_sb_price[(store, branch)] = price

            if not union_sb_price:
                continue

            # Mirror union; write only missing for each code
            for c in codes:
                c = str(c).strip()
                sb = sb_by_code.get(c) or {}
                for (store, branch), price in union_sb_price.items():
                    existing_price = None
                    if store in sb and sb[store] and branch in sb[store]:
                        existing_price = sb[store][branch]
                    if existing_price is not None:
                        continue

                    _queue_pair(c, store, branch, price)
                    total_pairs += 1

    # Pick strategy
    if len(dup_code_set) >= STORE_SCAN_DUP_CODE_THRESHOLD:
        _mirror_via_store_scan()
    else:
        _mirror_via_parallel_code_reads()

    if pending_items_stores:
        items_stores_ref.update(pending_items_stores)

    if pending_branch_count > 0:
        _flush_branch_updates()

    print(
        f"Regulated groups: {len(groups)} | Codes touched: {sum(len(v) for v in groups.values())} | Mirrored pairs: {total_pairs}"
    )

def regulate_single_item_name(name):
    new_name = str(name).strip()

    # normalize spaces & quotes to ASCII
    new_name = (
        new_name
        .replace("׳", "'")
        .replace("’", "'")
        .replace("'", "'")
        .replace("״", '"')
        .replace("“", '"')
        .replace("”", '"')
        .replace('"', '"')
    )

    # collapse repeated quotes/apostrophes (e.g., מ"" / ק'' / מ'" ) -> single char
    new_name = re.sub(r"(['\"]){2,}", r"\1", new_name)

    # -----------------------------
    # Spacing rules around numbers
    # -----------------------------

    # (1) Any Unicode letter followed by a number -> add space (e.g., "תה20" -> "תה 20")
    # [^\W\d_] = any unicode letter (not non-word, not digit, not underscore)
    new_name = re.sub(
        r"([^\W\d_])(?=\d)",
        r"\1 ",
        new_name,
        flags=re.UNICODE
    )

    # (2) Number followed by any Unicode letter -> add space (supports decimals with '_')
    # Do not touch percentages here (handled below)
    new_name = re.sub(
        r"(\d+(?:_\d+)?)(?=[^\W\d_])",
        r"\1 ",
        new_name,
        flags=re.UNICODE
    )

    # (3) Percent numbers stuck to text -> add space AFTER the %
    # "100%חלב" -> "100% חלב"
    new_name = re.sub(
        r"(\d+(?:_\d+)?)%(?=[^\W\d_])",
        r"\1% ",
        new_name,
        flags=re.UNICODE
    )

    # (4) Keep hyphen-number tight (e.g., "כ-500" should stay "כ-500")
    # If earlier rules created "כ- 500" by accident, fix it.
    new_name = re.sub(
        r"-\s+(?=\d)",
        "-",
        new_name
    )

    # -----------------------------
    # גרם (g)
    # -----------------------------

    # מספר + ג / גר / גרם / עם גרש
    new_name = re.sub(
        r"(\d+)\s*(?:גרם|גר|ג)'+\b",
        r"\1 גרם",
        new_name
    )
    new_name = re.sub(
        r"(\d+)\s*(?:גרם|גר|ג)\b",
        r"\1 גרם",
        new_name
    )

    # ג / גר כמילה לבד (עם או בלי גרש)
    new_name = re.sub(
        r"(?<=\s)(?:גר|ג)'+(?=\s|$)",
        "גרם",
        new_name
    )
    new_name = re.sub(
        r"(?<=\s)(גר|ג)(?=\s|$)",
        "גרם",
        new_name
    )

    # -----------------------------
    # קילוגרם → ק"ג
    # -----------------------------

    # מספר + קג / ק'ג / ק"ג (עם ה' אופציונלית)
    new_name = re.sub(
        r'(\d+(?:_\d+)?)\s*ה?(?:קג|ק\'ג|ק"ג|ק/ג|ק/"ג|קילוגרם|קילוגר|קילוג|קילו|ק\'|ק")\b',
        r'\1 ק"ג',
        new_name
    )

    # קג / ק'ג / ק"ג כמילה לבד
    new_name = re.sub(
        r'(?<=\s)ה?(?:קג|ק\'ג|ק"ג|ק/ג|ק/"ג|קילוגרם|קילוגר|קילוג|קילו|ק\'|ק")(?=\s|$)',
        'ק"ג',
        new_name
    )

    # -----------------------------
    # מיליליטר → מ"ל
    # -----------------------------

    # מספר + מל / מ'ל / מ"л (עם ה' אופציונלית)
    new_name = re.sub(
        r'(\d+(?:_\d+)?)\s*ה?(?:מל|מ\'ל|מ"ל)\b',
        r'\1 מ"ל',
        new_name
    )

    # מל / מ'ל / מ"л כמילה לבד
    new_name = re.sub(
        r'(?<=\s)ה?(?:מל|מ\'ל|מ"ל)(?=\s|$)',
        'מ"ל',
        new_name
    )

    # -----------------------------
    # מטר → מטר (מ')
    # -----------------------------

    # number + מ' / מ" (with optional ה) -> number מטר
    new_name = re.sub(
        r'(\d+(?:_\d+)?)\s*ה?(?:מ\'|מ")\b',
        r"\1 מטר",
        new_name
    )

    # standalone token -> מטר
    new_name = re.sub(
        r'(?<=\s)ה?(?:מ\'|מ")(?=\s|$)',
        "מטר",
        new_name
    )

    # -----------------------------
    # סנטימטר → ס"מ
    # -----------------------------

    # number + סמ / ס'מ / ס"м / ס' / ס" (with optional ה)
    new_name = re.sub(
        r'(\d+(?:_\d+)?)\s*ה?(?:סמ|ס\'מ|ס"מ|ס\'|ס")\b',
        r'\1 ס"מ',
        new_name
    )

    # standalone token -> ס"מ
    new_name = re.sub(
        r'(?<=\s)ה?(?:סמ|ס\'מ|ס"מ|ס\'|ס")(?=\s|$)',
        'ס"מ',
        new_name
    )

    # -----------------------------
    # יחידות (יח) → יחידות (only when at end)
    # -----------------------------

    # number + יח / יח" / יח' / יחיד / יחידו (end of string)
    new_name = re.sub(
        r'(\d+)\s*(?:יח|יח"|יח\'|יחיד|יחידו)\s*$',
        r"\1 יחידות",
        new_name
    )

    # standalone unit token at end -> יחידות
    new_name = re.sub(
        r'(?<=\s)(?:יח|יח"|יח\'|יחיד|יחידו)\s*$',
        "יחידות",
        new_name
    )

    # remove trailing encoded dots (one or many), but KEEP trailing '_'
    new_name = re.sub(r"(?:__dot__)+$", "", new_name)

    # final cleanup
    return re.sub(r"\s+", " ", new_name).strip()


def main():
    handler = User(is_admin=True)
    stores_branches = get_all_existing_stores()

    clear_all()
    print("\033c", end="")
    msg_bar_handler = msg_bar(len(stores_branches) + 2)
    handler.set_stores(list(stores_branches.keys()))
    handler.set_branches(stores_branches, msg_bar_handler=msg_bar_handler)
    update_all_stores(handler.handlers)
    regulate_item_names()
    
    msg_bar_handler.close()

if __name__ == "__main__":
    main()