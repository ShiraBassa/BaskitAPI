from tqdm import tqdm
from Data.data_sets import MSG_BAR_FORMAT

class msg_bar():
    def __init__(self, pos):
        self.bar = tqdm(total=0, position=pos, bar_format=MSG_BAR_FORMAT, leave=False, dynamic_ncols=True)
        self.message = ""
    
    def add_msg(self, msg, refresh=True):
        self.message = "---" + msg + "---"

        if refresh:
            self.refresh()
        
    def refresh(self):
        self.bar.set_description_str(self.message)
        self.bar.refresh()

    def close(self, final_msg=None):
        self.bar.close()

        if final_msg:
            tqdm.write(final_msg)