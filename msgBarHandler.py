from tqdm import tqdm


class msg_bar():
    def __init__(self):
        self.bar = tqdm(total=0, position=2, bar_format="{desc}", leave=False)
        self.messages = []
    
    def get_messages_str(self):
        return "\n".join(self.messages)

    def add_msg(self, msg, clear=False, refresh=True):
        self.messages.append("- " + msg)
        
        if clear:
            self.clear()

        if refresh:
            self.refresh()
        
    def refresh(self):
        self.bar.set_description_str(self.get_messages_str())
        self.bar.refresh()
    
    def clear(self):
        self.messages = []
        self.bar.set_description_str("")
        self.bar.refresh()

    def close(self, final_msg=None):
        self.bar.close()

        if final_msg:
            tqdm.write(final_msg)