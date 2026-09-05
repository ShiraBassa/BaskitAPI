from Data.data_sets import items_info_ref,items_categories_ref
class ClassificationCache:
    def load_product_classifications(self):
        try:
            data=items_info_ref.get() or {}; out={}
            for code,info in data.items():
                if not isinstance(info,dict): continue
                c=info.get('category'); g=info.get('general_group')
                if isinstance(c,str) and c.strip(): out[str(code)]={'category':c.strip(),**({'general_group':g.strip()} if isinstance(g,str) and g.strip() else {})}
            return out
        except Exception as e: print(f'[ERROR] Failed loading embedded classifications: {e}'); return {}
    def load_group_categories(self):
        try:
            data=items_info_ref.get() or {}; out={}
            for info in data.values():
                if isinstance(info,dict) and isinstance(info.get('general_group'),str) and isinstance(info.get('category'),str) and info['general_group'].strip() and info['category'].strip(): out[info['general_group'].strip()]=info['category'].strip()
            return out
        except Exception as e: print(f'[ERROR] Failed loading group categories: {e}'); return {}
    def save(self,updates):
        if not updates:return
        try:
            legacy={}; embedded={}
            for code,v in updates.items():
                if not isinstance(v,dict):continue
                if isinstance(v.get('category'),str) and v['category'].strip(): legacy[str(code)]=v['category'].strip(); embedded[f'{code}/category']=v['category'].strip()
                if isinstance(v.get('general_group'),str) and v['general_group'].strip(): embedded[f'{code}/general_group']=v['general_group'].strip()
            if legacy: items_categories_ref.update(legacy)
            if embedded: items_info_ref.update(embedded)
        except Exception as e: print(f'[ERROR] Failed saving classifications: {e}')
