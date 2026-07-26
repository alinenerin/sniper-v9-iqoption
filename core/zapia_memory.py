import os
from mem0 import Memory

class ZapiaMemory:
    """
    CAMADA DE MEMÓRIA INTELIGENTE (MEM0)
    Permite que a Zapia aprenda padrões, preferências e contexto da Aline.
    """
    def __init__(self, user_id="aline_tofoli"):
        self.user_id = user_id
        # Configuração básica para rodar localmente com SQLite/Qdrant
        self.memory = Memory()

    def learn(self, text):
        """Salva um novo aprendizado sobre a Aline."""
        self.memory.add(text, user_id=self.user_id)
        return "🧠 Aprendi algo novo sobre você!"

    def recall(self, query):
        """Busca memórias relacionadas a um assunto."""
        memories = self.memory.search(query, user_id=self.user_id)
        return memories

    def get_all(self):
        """Retorna tudo o que eu sei sobre a Aline."""
        return self.memory.get_all(user_id=self.user_id)

# Instância global para uso no sistema
zapia_brain = ZapiaMemory()
