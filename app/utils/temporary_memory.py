# インメモリキャッシュ
class TemporaryMemory:
    def __init__(self):
        self.memory = {}

    def set(self, key, value):
        self.memory[key] = value

    def get(self, key):
        return self.memory.get(key)

    def delete(self, key):
        del self.memory[key]
